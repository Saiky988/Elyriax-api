import asyncio
import logging
from app.core.database import execute, fetch_all
from app.core.security import decrypt
from app.services.genshin.checkin import check_in_daily
from app.services.genshin.codes import get_all_codes
from app.services.genshin.daily_note import get_daily_note
from app.services.genshin.redeem import redeem_code

logger = logging.getLogger("GenshinCronService")

async def run_auto_checkin():
    try:
        accounts = await fetch_all(
            """
            SELECT id, cookie, uid, server 
            FROM genshin_accounts 
            WHERE auto_checkin = TRUE AND status = 'active'
            """
        )
        for acc in accounts:
            try:
                cookie = decrypt(acc["cookie"])
                res = await check_in_daily({"cookie": cookie, "uid": acc["uid"], "server": acc["server"]})
                if res.get("ok"):
                    await execute("UPDATE genshin_accounts SET last_checkin_at = CURRENT_TIMESTAMP WHERE id = %s", (acc["id"],))
            except Exception as e:
                logger.warning(f"[AutoCheckin] Error for account {acc['id']}: {e}")
            await asyncio.sleep(3.0)
    except Exception as err:
        logger.error(f"[AutoCheckin] Root error: {err}")

async def run_auto_redeem():
    try:
        cards = await get_all_codes()
        active_codes = []
        for card in cards:
            if card.get("codes"):
                active_codes.extend(card["codes"])

        if not active_codes:
            return

        accounts = await fetch_all(
            """
            SELECT id, cookie, uid, server 
            FROM genshin_accounts 
            WHERE auto_redeem = TRUE AND status = 'active'
            """
        )
        for acc in accounts:
            try:
                cookie = decrypt(acc["cookie"])
                for code in active_codes:
                    await redeem_code({"cookie": cookie, "server": acc["server"], "code": code})
                    await asyncio.sleep(2.0)

                await execute("UPDATE genshin_accounts SET last_redeem_at = CURRENT_TIMESTAMP WHERE id = %s", (acc["id"],))
            except Exception as e:
                logger.warning(f"[AutoRedeem] Error for account {acc['id']}: {e}")
            await asyncio.sleep(3.0)
    except Exception as err:
        logger.error(f"[AutoRedeem] Root error: {err}")

async def run_auto_daily_note():
    try:
        accounts = await fetch_all(
            """
            SELECT id, cookie, uid, server 
            FROM genshin_accounts 
            WHERE auto_daily_note = TRUE AND status = 'active'
            """
        )
        for acc in accounts:
            try:
                cookie = decrypt(acc["cookie"])
                res = await get_daily_note({"cookie": cookie, "uid": acc["uid"], "server": acc["server"]})
                if res.get("ok"):
                    await execute("UPDATE genshin_accounts SET last_daily_note_at = CURRENT_TIMESTAMP WHERE id = %s", (acc["id"],))
            except Exception as e:
                logger.warning(f"[AutoDailyNote] Error for account {acc['id']}: {e}")
            await asyncio.sleep(2.0)
    except Exception as err:
        logger.error(f"[AutoDailyNote] Root error: {err}")
