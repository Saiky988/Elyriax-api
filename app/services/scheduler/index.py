import asyncio
import logging
from datetime import datetime, timezone, timedelta
from app.services.scheduler.genshin_scheduler import run_genshin_auto_checkin
from app.services.scheduler.genshin_cron_service import run_auto_daily_note, run_auto_redeem

logger = logging.getLogger("Scheduler")

async def scheduler_loop():
    logger.info("[SCHEDULER] Booting up cron jobs...")
    tz_vn = timezone(timedelta(hours=7))
    last_checkin_day = None
    last_redeem_hour = None
    last_note_minute = None

    while True:
        try:
            now_vn = datetime.now(tz_vn)
            current_day = now_vn.date()
            current_hour = now_vn.hour
            current_minute = now_vn.minute

            # 1. Auto Checkin at 00:05 (and backup at 06:00)
            if (current_hour == 0 and current_minute >= 5) or (current_hour == 6 and current_minute >= 0):
                if last_checkin_day != (current_day, current_hour):
                    last_checkin_day = (current_day, current_hour)
                    asyncio.create_task(run_genshin_auto_checkin())

            # 2. Auto Redeem at 12:00 and 20:00
            if current_hour in [12, 20] and current_minute == 0:
                if last_redeem_hour != (current_day, current_hour):
                    last_redeem_hour = (current_day, current_hour)
                    asyncio.create_task(run_auto_redeem())

            # 3. Auto Daily Note every 30 mins (minute 0 and 30)
            if current_minute in [0, 30]:
                if last_note_minute != (current_day, current_hour, current_minute):
                    last_note_minute = (current_day, current_hour, current_minute)
                    asyncio.create_task(run_auto_daily_note())

            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[SCHEDULER ERROR]: {e}")
            await asyncio.sleep(60)

def start_schedulers() -> asyncio.Task:
    return asyncio.create_task(scheduler_loop())
