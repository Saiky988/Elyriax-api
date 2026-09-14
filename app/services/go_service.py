import json
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from app.core.config import settings

ALLOWED_DEVICES = {"pc", "mb", "tv"}
ALLOWED_DOMAINS = {"netflix.com", "www.netflix.com"}

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "go_database.json"

def read_db() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_db(data: Dict[str, Any]):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_id(length: int = 10) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(chars) for _ in range(length))

def create_go_link(url: str, device: str, expires_in: int = 3600) -> Dict[str, Any]:
    if device not in ALLOWED_DEVICES:
        raise ValueError("Invalid device. Allowed: pc, mb, tv")

    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("Invalid URL format.")

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS URLs are allowed.")

    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_DOMAINS:
        raise ValueError("Destination domain is not allowed.")

    valid_expires_in = max(1, int(expires_in or 3600))
    link_id = generate_id(10)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=valid_expires_in)).isoformat()

    db = read_db()
    db[link_id] = {
        "id": link_id,
        "device": device,
        "destination": url,
        "createdAt": now.isoformat(),
        "expiresAt": expires_at,
    }
    write_db(db)

    base_url = settings.GO_BASE_URL or "https://go.elyriax.com"
    return {
        "success": True,
        "id": link_id,
        "device": device,
        "expiresAt": expires_at,
        "url": f"{base_url}/n/{device}/{link_id}",
    }

def get_go_metadata(link_id: str) -> Optional[Dict[str, Any]]:
    db = read_db()
    item = db.get(link_id)
    if not item:
        return None

    try:
        exp_dt = datetime.fromisoformat(item["expiresAt"].replace("Z", "+00:00"))
        is_expired = datetime.now(timezone.utc) >= exp_dt
    except Exception:
        is_expired = False

    return {
        "id": item["id"],
        "device": item["device"],
        "createdAt": item.get("createdAt"),
        "expiresAt": item.get("expiresAt"),
        "expired": is_expired,
    }

def resolve_redirect(device: str, link_id: str) -> Optional[str]:
    db = read_db()
    item = db.get(link_id)
    if not item or item.get("device") != device:
        return None

    try:
        exp_dt = datetime.fromisoformat(item["expiresAt"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= exp_dt:
            db.pop(link_id, None)
            write_db(db)
            return None
    except Exception:
        pass

    return item.get("destination")
