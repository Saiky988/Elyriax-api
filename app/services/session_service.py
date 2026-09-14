import secrets
from typing import Any, Dict, Optional
from fastapi import Request
from app.core.database import execute, fetch_all, fetch_one
from app.core.security import hash_token

def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None

async def create_session(user_id: int, request: Request, remember_me: bool = False) -> str:
    session_token = secrets.token_hex(32)
    token_hash = hash_token(session_token)
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    days = 365 if remember_me else 7

    await execute(
        """
        INSERT INTO sessions 
        (user_id, token_hash, ip, user_agent, remember_me, expires_at) 
        VALUES (%s, %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL %s DAY))
        """,
        (user_id, token_hash, ip, user_agent, remember_me, days),
    )
    return session_token

async def verify_session(session_token: str) -> Optional[Dict[str, Any]]:
    if not session_token:
        return None

    token_hash = hash_token(session_token)
    session = await fetch_one(
        """
        SELECT user_id FROM sessions 
        WHERE token_hash = %s AND revoked = FALSE AND expires_at > NOW()
        """,
        (token_hash,),
    )
    if not session:
        return None

    user_id = session["user_id"]
    try:
        await execute("UPDATE sessions SET last_seen = NOW() WHERE token_hash = %s", (token_hash,))
    except Exception:
        pass

    user = await fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
    if not user:
        return None

    providers = await fetch_all("SELECT provider FROM user_oauth_accounts WHERE user_id = %s", (user_id,))
    user["providers"] = [p["provider"] for p in providers]
    return user

async def revoke_session(session_token: str):
    if not session_token:
        return
    token_hash = hash_token(session_token)
    await execute("UPDATE sessions SET revoked = TRUE WHERE token_hash = %s", (token_hash,))

async def revoke_all_user_sessions(user_id: int):
    await execute("UPDATE sessions SET revoked = TRUE WHERE user_id = %s", (user_id,))
