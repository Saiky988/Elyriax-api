from typing import Any, Dict, Optional
import httpx

ACT_ID = "e202102251931481"
HOYO_API = {
    "HOME": "https://sg-hk4e-api.hoyolab.com/event/sol/home",
    "INFO": "https://sg-hk4e-api.hoyolab.com/event/sol/info",
    "SIGN": "https://sg-hk4e-api.hoyolab.com/event/sol/sign",
    "ROLE": "https://api-os-takumi.hoyoverse.com/binding/api/getUserGameRolesByCookie",
}

REGION_MAP = {
    "asia": "os_asia",
    "america": "os_usa",
    "usa": "os_usa",
    "na": "os_usa",
    "europe": "os_euro",
    "eu": "os_euro",
    "tw": "os_cht",
    "hk": "os_cht",
    "os_asia": "os_asia",
    "os_usa": "os_usa",
    "os_euro": "os_euro",
    "os_cht": "os_cht",
}

SERVER_NAME_MAP = {
    "os_asia": "Asia",
    "os_usa": "NA",
    "os_euro": "EU",
    "os_cht": "TW/HK",
}

async def check_in_daily(payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie")
    server = payload.get("server", "")
    discord_id = payload.get("discord_id")

    if not cookie:
        raise ValueError("Missing cookie")

    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    target_region = REGION_MAP.get(server.lower())
    if not target_region:
        raise ValueError("Invalid server provided")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Fetch awards
        home_res = await client.get(f"{HOYO_API['HOME']}?act_id={ACT_ID}", headers=headers)
        home_data = home_res.json()
        if home_data.get("retcode") != 0:
            raise ValueError(home_data.get("message") or "Home API Error")

        awards = home_data.get("data", {}).get("awards", [])
        total_days_month = len(awards)

        # 2. Fetch current sign status
        info_res = await client.get(f"{HOYO_API['INFO']}?act_id={ACT_ID}", headers=headers)
        info_data = info_res.json()
        if info_data.get("retcode") != 0:
            raise ValueError(info_data.get("message") or "Info API Error")

        total_signed = info_data.get("data", {}).get("total_sign_day", 0)
        is_signed = info_data.get("data", {}).get("is_sign", False)
        claimed = False
        risk_code = 0

        # 3. Perform Sign if needed
        if not is_signed:
            sign_res = await client.post(HOYO_API["SIGN"], headers=headers, json={"act_id": ACT_ID})
            sign_data = sign_res.json()
            risk_code = sign_data.get("risk_code", 0)

            if sign_data.get("retcode") == 0:
                claimed = True
                total_signed += 1
            elif sign_data.get("retcode") != -5003:
                raise ValueError(sign_data.get("message") or "Sign API Error")

        today_index = max(total_signed - 1, 0)
        today_reward = awards[today_index] if today_index < len(awards) else None
        tomorrow_reward = awards[total_signed] if total_signed < len(awards) else None

        # 4. Fetch Role Information
        role_res = await client.get(f"{HOYO_API['ROLE']}?game_biz=hk4e_global", headers=headers)
        role_data = role_res.json()
        if role_data.get("retcode") != 0:
            raise ValueError("Failed to fetch account list")

        roles = role_data.get("data", {}).get("list", [])
        selected_role = None
        for r in roles:
            if r.get("region") == target_region:
                selected_role = r
                break

        if not selected_role:
            raise ValueError(f"No account found on server: {server}")

        return {
            "ok": True,
            "claimed": claimed,
            "discord_id": discord_id or None,
            "nickname": selected_role.get("nickname"),
            "uid": selected_role.get("game_uid"),
            "server": SERVER_NAME_MAP.get(selected_role.get("region"), selected_role.get("region")),
            "adventure_rank": selected_role.get("level"),
            "signed_days": total_signed,
            "total_days_month": total_days_month,
            "missing_days": max(total_days_month - total_signed, 0),
            "today_reward": {
                "name": today_reward.get("name"),
                "count": today_reward.get("cnt"),
                "icon": today_reward.get("icon"),
            } if today_reward else None,
            "tomorrow_reward": {
                "name": tomorrow_reward.get("name"),
                "count": tomorrow_reward.get("cnt"),
                "icon": tomorrow_reward.get("icon"),
            } if tomorrow_reward else None,
            "risk_code": risk_code,
        }
