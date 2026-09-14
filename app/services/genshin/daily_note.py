from datetime import datetime, timezone, timedelta
from typing import Any, Dict
import httpx

def calculate_estimated_time(seconds_remaining: int) -> str:
    if not seconds_remaining or seconds_remaining <= 0:
        return "Đã đầy/Xong"
    now = datetime.now()
    future = now + timedelta(seconds=seconds_remaining)

    is_today = now.date() == future.date()
    hours = f"{future.hour:02d}"
    minutes = f"{future.minute:02d}"

    return f"Hôm nay {hours}:{minutes}" if is_today else f"Ngày mai {hours}:{minutes}"

async def get_daily_note(payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie")
    uid = payload.get("uid")
    server = payload.get("server")

    if not cookie or not uid or not server:
        return {"ok": False, "error": "Thiếu cookie, uid hoặc server"}

    try:
        url = f"https://sg-act-public-api.hoyolab.com/event/game_record/app/genshin/api/dailyNote?server={server}&role_id={uid}"
        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) miHoYoBBS/2.50.1",
            "X-Rpc-Client_type": "2",
            "X-Rpc-App_version": "2.50.1",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, headers=headers)
            res_data = res.json()

        if res_data.get("retcode") != 0:
            return {
                "ok": False,
                "error": res_data.get("message") or "Không thể lấy dữ liệu từ HoYoLAB",
                "retcode": res_data.get("retcode"),
            }

        raw = res_data.get("data", {})
        resin_rec_sec = int(raw.get("resin_recovery_time") or 0)
        home_coin_rec_sec = int(raw.get("home_coin_recovery_time") or 0)

        processed = {
            "resin": {
                "current": raw.get("current_resin"),
                "max": raw.get("max_resin"),
                "is_full": raw.get("current_resin") == raw.get("max_resin"),
                "recovery_time_seconds": resin_rec_sec,
                "estimated_full_time": calculate_estimated_time(resin_rec_sec),
                "resin_discount": {
                    "remain_num": raw.get("remain_resin_discount_num", 0),
                    "limit_num": raw.get("resin_discount_num_limit", 3),
                    "is_used_up": raw.get("remain_resin_discount_num", 0) == 0,
                },
            },
            "daily_tasks": {
                "finished_num": raw.get("finished_task_num"),
                "total_num": raw.get("total_task_num"),
                "is_extra_reward_received": raw.get("is_extra_task_reward_received"),
                "is_all_finished": raw.get("finished_task_num") == raw.get("total_task_num") and raw.get("is_extra_task_reward_received"),
                "task_rewards": raw.get("daily_task", {}).get("task_rewards", []),
                "attendance_rewards": raw.get("daily_task", {}).get("attendance_rewards", []),
                "attendance_visible": raw.get("daily_task", {}).get("attendance_visible", True),
                "stored_attendance": float(raw.get("daily_task", {}).get("stored_attendance") or raw.get("stored_attendance") or "0"),
                "stored_attendance_refresh_countdown_seconds": raw.get("daily_task", {}).get("stored_attendance_refresh_countdown", 0),
                "estimated_refresh_time": calculate_estimated_time(raw.get("daily_task", {}).get("stored_attendance_refresh_countdown", 0)),
            },
            "expeditions": {
                "current_num": raw.get("current_expedition_num"),
                "max_num": raw.get("max_expedition_num"),
                "list": [
                    {
                        "avatar_icon": exp.get("avatar_side_icon"),
                        "status": exp.get("status"),
                        "remained_time_seconds": int(exp.get("remained_time") or 0),
                        "estimated_finished_time": calculate_estimated_time(int(exp.get("remained_time") or 0)),
                    }
                    for exp in raw.get("expeditions", [])
                ],
            },
            "home_coin": {
                "current": raw.get("current_home_coin"),
                "max": raw.get("max_home_coin"),
                "is_full": raw.get("current_home_coin") == raw.get("max_home_coin"),
                "recovery_time_seconds": home_coin_rec_sec,
                "estimated_full_time": calculate_estimated_time(home_coin_rec_sec),
            },
            "transformer": {
                "obtained": raw.get("transformer", {}).get("obtained", False),
                "ready": raw.get("transformer", {}).get("recovery_time", {}).get("reached", False),
                "recovery_time": raw.get("transformer", {}).get("recovery_time") or {"Day": 0, "Hour": 0, "Minute": 0, "Second": 0, "reached": True},
                "latest_job_id": raw.get("transformer", {}).get("latest_job_id", "0"),
            },
            "archon_quest_progress": {
                "is_open": raw.get("archon_quest_progress", {}).get("is_open_archon_quest", True),
                "is_finish_all_mainline": raw.get("archon_quest_progress", {}).get("is_finish_all_mainline", False),
                "is_finish_all_interchapter": raw.get("archon_quest_progress", {}).get("is_finish_all_interchapter", False),
                "list": raw.get("archon_quest_progress", {}).get("list", []),
            },
            "week_active_progress": {
                "unlock": raw.get("week_active_progress", {}).get("unlock", False),
                "progress_current": raw.get("week_active_progress", {}).get("progress_current", 0),
                "progress_total": raw.get("week_active_progress", {}).get("progress_total", 5),
                "period_progress_current": raw.get("week_active_progress", {}).get("period_progress_current", 0),
                "period_progress_total": raw.get("week_active_progress", {}).get("period_progress_total", 8),
                "current_weekday": raw.get("week_active_progress", {}).get("current_weekday", 0),
                "is_active_period": raw.get("week_active_progress", {}).get("is_active_period", False),
            },
            "calendar_url": raw.get("calendar_url", ""),
        }
        return {"ok": True, "data": processed}
    except Exception as e:
        return {"ok": False, "error": str(e)}
