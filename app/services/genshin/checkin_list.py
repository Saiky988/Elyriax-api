import asyncio
from typing import Any, Dict
import httpx

ACT_ID = "e202102251931481"

async def get_check_in_list(payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie", "")
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-rpc-signgame": "hk4e",
        "x-rpc-client_type": "4",
    }

    home_api = f"https://sg-act-public-api.hoyolab.com/event/sol/home?lang=vi-vn&act_id={ACT_ID}"
    extra_api = f"https://sg-act-public-api.hoyolab.com/event/sol/extra_award?lang=vi-vn&act_id={ACT_ID}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        home_task = client.get(home_api, headers=headers)
        extra_task = client.get(extra_api, headers=headers)
        home_res, extra_res = await asyncio.gather(home_task, extra_task)

        home_json = home_res.json()
        extra_json = extra_res.json()

        if home_json.get("retcode") != 0:
            return {
                "ok": False,
                "retcode": home_json.get("retcode"),
                "message": home_json.get("message") or "Failed to fetch main check-in awards",
            }

        monthly_awards = [
            {
                "day": idx + 1,
                "name": award.get("name"),
                "count": award.get("cnt"),
                "icon": award.get("icon"),
            }
            for idx, award in enumerate(home_json.get("data", {}).get("awards", []))
        ]

        extra_awards = [
            {
                "id": extra.get("id"),
                "sign_day_required": extra.get("sign_day"),
                "count": extra.get("cnt"),
                "icon": extra.get("icon"),
                "is_highlight": extra.get("highlight", False),
            }
            for extra in extra_json.get("data", {}).get("awards", [])
        ]

        return {
            "ok": True,
            "month": home_json.get("data", {}).get("month"),
            "now_timestamp": home_json.get("data", {}).get("now"),
            "resign_available": home_json.get("data", {}).get("resign", False),
            "monthly_awards": monthly_awards,
            "extra_awards": extra_awards,
            "has_month_card": extra_json.get("data", {}).get("mc", {}).get("has_month_card", False),
        }
