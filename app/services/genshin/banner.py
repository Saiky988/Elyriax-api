import json
from pathlib import Path
from typing import Any, Dict, List, Optional

BANNERS_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "banners.json"

async def get_banners() -> List[Dict[str, Any]]:
    if not BANNERS_FILE_PATH.exists():
        return []
    try:
        with open(BANNERS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Không thể tải data banner: {e}")

async def get_active_banner() -> Optional[Dict[str, Any]]:
    banners = await get_banners()
    for b in banners:
        if b.get("going_on") is True:
            return b
    return None
