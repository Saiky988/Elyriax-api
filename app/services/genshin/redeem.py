from typing import Any, Dict
from urllib.parse import urlencode
import httpx
from app.services.genshin.codes import get_code_info

HOYO_API = {
    "ROLE": "https://api-os-takumi.hoyoverse.com/binding/api/getUserGameRolesByCookie",
    "REDEEM": "https://public-operation-hk4e.hoyoverse.com/common/apicdkey/api/webExchangeCdkey",
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
}

async def redeem_code(payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie")
    server = payload.get("server", "")
    code = payload.get("code")

    if not cookie or not server or not code:
        raise ValueError("Missing cookie, server, or code")

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
        role_res = await client.get(f"{HOYO_API['ROLE']}?game_biz=hk4e_global", headers=headers)
        role_data = role_res.json()
        if role_data.get("retcode") != 0:
            raise ValueError("Invalid cookie or failed to fetch account list")

        roles = role_data.get("data", {}).get("list", [])
        selected_role = None
        for r in roles:
            if r.get("region") == target_region:
                selected_role = r
                break

        if not selected_role:
            raise ValueError(f"No account found on server: {server}")

        uid = selected_role.get("game_uid")
        region = selected_role.get("region")

        params = {
            "uid": uid,
            "region": region,
            "lang": "en",
            "cdkey": code,
            "game_biz": "hk4e_global",
            "sLangKey": "en-us",
        }

        redeem_res = await client.get(f"{HOYO_API['REDEEM']}?{urlencode(params)}", headers=headers)
        redeem_data = redeem_res.json()

        if redeem_data.get("retcode") != 0:
            return {
                "ok": False,
                "error": redeem_data.get("message") or "Redemption failed",
                "retcode": redeem_data.get("retcode"),
            }

        code_info = await get_code_info(code)

        return {
            "ok": True,
            "message": redeem_data.get("data", {}).get("msg") or "Success",
            "uid": uid,
            "server": server.capitalize(),
            "code": code,
            "rewards": code_info.get("rewards", []),
            "validity": code_info.get("validity"),
        }
