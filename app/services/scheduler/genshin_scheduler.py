import asyncio
import logging
from datetime import datetime, timezone, timedelta
from app.services.genshin.account_service import (
    get_auto_checkin_accounts,
    get_ready_genshin_payload,
    update_checkin_status,
)
from app.services.genshin.checkin import check_in_daily
from app.services.email_service import render_template, send_notification_email

logger = logging.getLogger("GenshinScheduler")

def already_processed_today(last_checkin_at) -> bool:
    if not last_checkin_at:
        return False
    tz_vn = timezone(timedelta(hours=7))
    today_vn = datetime.now(tz_vn).date()

    if isinstance(last_checkin_at, str):
        try:
            checkin_dt = datetime.fromisoformat(last_checkin_at.replace("Z", "+00:00"))
        except Exception:
            return False
    else:
        checkin_dt = last_checkin_at

    if hasattr(checkin_dt, "astimezone"):
        checkin_date = checkin_dt.astimezone(tz_vn).date()
    else:
        checkin_date = checkin_dt.date()

    return today_vn == checkin_date

async def run_genshin_auto_checkin():
    logger.info("[GENSHIN CHECKIN] Scheduler started")
    try:
        accounts = await get_auto_checkin_accounts()
        logger.info(f"[GENSHIN CHECKIN] Found {len(accounts)} accounts to process")
    except Exception as e:
        logger.error(f"[GENSHIN CHECKIN ERROR] Cannot fetch accounts: {e}")
        return

    for account in accounts:
        if already_processed_today(account.get("last_checkin_at")):
            continue

        acc_id = account["id"]
        uid = account["uid"]
        user_id = account["user_id"]
        logger.info(f"[GENSHIN CHECKIN] Processing account #{acc_id} | UID: {uid}")

        try:
            payload = await get_ready_genshin_payload(user_id, acc_id)
            result = await check_in_daily(payload)

            status_str = "error"
            if result.get("risk_code", 0) > 0:
                status_str = "captcha"
            elif result.get("claimed") is True:
                status_str = "success"
            else:
                status_str = "already_claimed"

            await update_checkin_status(acc_id, status_str)

            if status_str == "success" and account.get("email"):
                try:
                    today_reward = result.get("today_reward") or {}
                    tomorrow_reward = result.get("tomorrow_reward") or {}
                    html = render_template(
                        "templates/email/genshin-checkin-success.html",
                        {
                            "nickname": result.get("nickname") or account.get("nickname"),
                            "uid": result.get("uid") or uid,
                            "today_reward_name": today_reward.get("name"),
                            "today_reward_count": today_reward.get("count"),
                            "signed_days": result.get("signed_days"),
                            "total_days_month": result.get("total_days_month"),
                            "tomorrow_reward_name": tomorrow_reward.get("name"),
                            "tomorrow_reward_count": tomorrow_reward.get("count"),
                        },
                    )
                    await send_notification_email(
                        to=account["email"],
                        subject=f"[Genshin] Điểm danh hàng ngày thành công — {result.get('nickname') or account.get('nickname')}",
                        html=html,
                    )
                    logger.info(f"[GENSHIN CHECKIN] Email sent | UID: {uid}")
                except Exception as email_err:
                    logger.error(f"[GENSHIN CHECKIN EMAIL ERROR] UID: {uid} | {email_err}")

        except Exception as err:
            err_msg = str(err).lower()
            status_str = "error"
            if "cookie" in err_msg or "login" in err_msg or "account" in err_msg:
                status_str = "cookie_expired"
            elif "risk" in err_msg or "captcha" in err_msg:
                status_str = "captcha"

            logger.error(f"[GENSHIN CHECKIN ERROR] Account #{acc_id} | UID: {uid} | Status: {status_str} | Msg: {err}")
            try:
                await update_checkin_status(acc_id, status_str)
            except Exception:
                pass

        await asyncio.sleep(3.0)

    logger.info("[GENSHIN CHECKIN] Scheduler finished")
