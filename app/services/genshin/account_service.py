from typing import Any, Dict, List, Optional
from app.core.database import execute, fetch_all, fetch_one, get_connection
from app.core.security import decrypt, encrypt
from app.services.genshin.stats import get_role_and_stats

async def add_account(user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie", "")
    uid = payload.get("uid", "")
    server = payload.get("server", "")

    stats_res = await get_role_and_stats({"cookie": cookie, "uid": uid, "server": server})
    if not stats_res.get("ok"):
        raise ValueError("Xác thực HoYoLAB thất bại. Cookie, UID hoặc Server không hợp lệ.")

    nickname = stats_res.get("role", {}).get("nickname", "")
    encrypted_cookie = encrypt(cookie)

    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    'SELECT COUNT(id) as count FROM genshin_accounts WHERE user_id = %s AND status != "deleted"',
                    (user_id,),
                )
                count_row = await cur.fetchone()
                is_default = (count_row["count"] == 0)

                await cur.execute(
                    """
                    INSERT INTO genshin_accounts (user_id, nickname, uid, server, cookie, is_default) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, nickname, uid, server, encrypted_cookie, is_default),
                )
                account_id = cur.lastrowid
                await conn.commit()

                return {
                    "id": account_id,
                    "nickname": nickname,
                    "uid": uid,
                    "server": server,
                    "is_default": is_default,
                }
            except Exception:
                await conn.rollback()
                raise

async def get_accounts(user_id: int) -> List[Dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT id, nickname, uid, server, is_default, auto_checkin, auto_redeem, auto_daily_note, status 
        FROM genshin_accounts 
        WHERE user_id = %s AND status != 'deleted' 
        ORDER BY is_default DESC, created_at DESC
        """,
        (user_id,),
    )
    for r in rows:
        r["is_default"] = bool(r.get("is_default"))
        r["auto_checkin"] = bool(r.get("auto_checkin"))
        r["auto_redeem"] = bool(r.get("auto_redeem"))
        r["auto_daily_note"] = bool(r.get("auto_daily_note"))
    return rows

async def get_account_by_id(user_id: int, account_id: int) -> Dict[str, Any]:
    row = await fetch_one(
        """
        SELECT id, nickname, uid, server, is_default, auto_checkin, auto_redeem, auto_daily_note, 
               last_checkin_at, last_redeem_at, last_daily_note_at, status 
        FROM genshin_accounts 
        WHERE id = %s AND user_id = %s AND status != 'deleted'
        """,
        (account_id, user_id),
    )
    if not row:
        raise ValueError("Tài khoản không tồn tại hoặc đã bị xóa.")

    res = dict(row)
    res["is_default"] = bool(res.get("is_default"))
    res["auto_checkin"] = bool(res.get("auto_checkin"))
    res["auto_redeem"] = bool(res.get("auto_redeem"))
    res["auto_daily_note"] = bool(res.get("auto_daily_note"))
    if res.get("last_checkin_at") and hasattr(res["last_checkin_at"], "isoformat"):
        res["last_checkin_at"] = res["last_checkin_at"].isoformat()
    if res.get("last_redeem_at") and hasattr(res["last_redeem_at"], "isoformat"):
        res["last_redeem_at"] = res["last_redeem_at"].isoformat()
    if res.get("last_daily_note_at") and hasattr(res["last_daily_note_at"], "isoformat"):
        res["last_daily_note_at"] = res["last_daily_note_at"].isoformat()
    return res

async def update_account(user_id: int, account_id: int, data: Dict[str, Any]):
    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "SELECT id FROM genshin_accounts WHERE id = %s AND user_id = %s FOR UPDATE",
                    (account_id, user_id),
                )
                acc = await cur.fetchone()
                if not acc:
                    raise ValueError("Tài khoản không tồn tại.")

                if data.get("is_default") is True:
                    await cur.execute("UPDATE genshin_accounts SET is_default = false WHERE user_id = %s", (user_id,))

                updates = []
                params = []
                for f in ["auto_checkin", "auto_redeem", "auto_daily_note", "is_default", "status"]:
                    if f in data:
                        updates.append(f"{f} = %s")
                        val = data[f]
                        if isinstance(val, bool):
                            params.append(val)
                        else:
                            params.append(val)

                if updates:
                    params.extend([account_id, user_id])
                    sql = f"UPDATE genshin_accounts SET {', '.join(updates)} WHERE id = %s AND user_id = %s"
                    await cur.execute(sql, tuple(params))

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def delete_account(user_id: int, account_id: int):
    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    'SELECT is_default FROM genshin_accounts WHERE id = %s AND user_id = %s AND status != "deleted" FOR UPDATE',
                    (account_id, user_id),
                )
                acc = await cur.fetchone()
                if not acc:
                    raise ValueError("Tài khoản không tồn tại.")

                was_default = bool(acc.get("is_default"))
                await cur.execute(
                    'UPDATE genshin_accounts SET status = "deleted", is_default = false WHERE id = %s',
                    (account_id,),
                )

                if was_default:
                    await cur.execute(
                        """
                        UPDATE genshin_accounts SET is_default = true 
                        WHERE user_id = %s AND status = 'active' 
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (user_id,),
                    )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def get_ready_genshin_payload(user_id: int, account_id: int) -> Dict[str, Any]:
    row = await fetch_one(
        'SELECT cookie, uid, server FROM genshin_accounts WHERE id = %s AND user_id = %s AND status = "active"',
        (account_id, user_id),
    )
    if not row:
        raise ValueError("Tài khoản Genshin không khả dụng.")

    raw_cookie = decrypt(row["cookie"])
    return {
        "cookie": raw_cookie,
        "uid": row["uid"],
        "server": row["server"],
    }

async def get_auto_checkin_accounts() -> List[Dict[str, Any]]:
    return await fetch_all(
        """
        SELECT 
            ga.id, 
            ga.user_id, 
            ga.nickname, 
            ga.uid, 
            ga.server, 
            ga.last_checkin_at, 
            ga.last_checkin_status,
            u.email,
            u.username
        FROM genshin_accounts ga
        INNER JOIN users u ON u.id = ga.user_id
        WHERE ga.status = 'active' 
          AND ga.auto_checkin = 1 
          AND u.status = 'active'
        """
    )

async def update_checkin_status(account_id: int, status_str: str):
    await execute(
        """
        UPDATE genshin_accounts 
        SET last_checkin_at = NOW(), last_checkin_status = %s 
        WHERE id = %s
        """,
        (status_str, account_id),
    )
