import secrets
from typing import Any, Dict, Optional
from app.core.database import execute, fetch_one, get_connection
from app.core.security import hash_key

PREFIX = "sk_syr_"

async def get_or_create_api_key(user_id: int) -> Dict[str, Any]:
    existing = await fetch_one(
        "SELECT created_at, last_used FROM api_keys WHERE user_id = %s",
        (user_id,)
    )
    if existing:
        return {
            "success": True,
            "message": "Bạn đã tạo API Key rồi.",
            "data": {
                "created_at": existing["created_at"].isoformat() if hasattr(existing["created_at"], "isoformat") else str(existing["created_at"]),
                "last_used": existing["last_used"].isoformat() if existing["last_used"] and hasattr(existing["last_used"], "isoformat") else (str(existing["last_used"]) if existing["last_used"] else None),
            },
        }

    random_hex = secrets.token_hex(24)
    raw_key = PREFIX + random_hex
    hashed_key = hash_key(raw_key)

    await execute(
        "INSERT INTO api_keys (user_id, name, key_hash) VALUES (%s, %s, %s)",
        (user_id, "Default Key", hashed_key),
    )

    return {
        "success": True,
        "api_key": raw_key,
    }

async def get_api_key_info(user_id: int) -> Optional[Dict[str, Any]]:
    row = await fetch_one(
        "SELECT created_at, last_used FROM api_keys WHERE user_id = %s",
        (user_id,)
    )
    if not row:
        return None
    return {
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "last_used": row["last_used"].isoformat() if row["last_used"] and hasattr(row["last_used"], "isoformat") else (str(row["last_used"]) if row["last_used"] else None),
    }

async def delete_api_key(user_id: int) -> bool:
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM api_keys WHERE user_id = %s", (user_id,))
            return cur.rowcount > 0

async def validate_api_key(raw_key: str) -> Optional[int]:
    if not raw_key or not raw_key.startswith(PREFIX):
        return None

    hashed_key = hash_key(raw_key)
    row = await fetch_one("SELECT user_id FROM api_keys WHERE key_hash = %s", (hashed_key,))
    if not row:
        return None

    user_id = row["user_id"]
    try:
        await execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE user_id = %s", (user_id,))
    except Exception:
        pass

    return user_id
