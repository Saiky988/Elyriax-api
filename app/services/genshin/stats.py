from typing import Any, Dict
import httpx

async def get_role_and_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    cookie = payload.get("cookie")
    uid = payload.get("uid")
    server = payload.get("server")

    if not cookie or not uid or not server:
        raise ValueError("Missing required parameters: cookie, uid, or server")

    headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "x-rpc-client_type": "5",
        "x-rpc-app_version": "1.5.0",
        "x-rpc-language": "vi-vn",
        "x-rpc-env": "default",
        "x-rpc-lang": "vi-vn",
        "x-rpc-device_id": "3d6d7575-0aa3-4f16-b913-ed082eaf7074",
        "x-rpc-device_fp": "38d7f7634fe00",
        "x-rpc-platform": "5",
        "x-rpc-page": "v6.7.1-gr-sea_#/ys",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
    }

    url = f"https://sg-act-public-api.hoyolab.com/event/game_record/genshin/api/index?avatar_list_type=1&server={server}&role_id={uid}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers)
        res_data = res.json()

    if res_data.get("retcode") != 0:
        return {
            "ok": False,
            "retcode": res_data.get("retcode"),
            "message": res_data.get("message") or "Failed to fetch data from HoYoLab API",
        }

    data = res_data.get("data", {})
    role_data = data.get("role", {})
    stats_data = data.get("stats", {})

    avatars = []
    for av in data.get("avatars", []):
        weapon_data = av.get("weapon")
        weapon = {
            "name": weapon_data.get("name"),
            "level": weapon_data.get("level"),
            "rarity": weapon_data.get("rarity"),
            "affix_level": weapon_data.get("affix_level"),
        } if weapon_data else None

        relics = [
            {
                "name": re.get("name"),
                "pos_name": re.get("pos_name"),
                "rarity": re.get("rarity"),
                "level": re.get("level"),
                "set_name": re.get("set", {}).get("name"),
            }
            for re in av.get("relics", [])
        ]

        avatars.append({
            "id": av.get("id"),
            "name": av.get("name"),
            "element": av.get("element"),
            "level": av.get("level"),
            "rarity": av.get("rarity"),
            "fetter": av.get("fetter"),
            "constellation": av.get("actived_constellation_num"),
            "image": av.get("image"),
            "weapon": weapon,
            "relics": relics,
        })

    return {
        "ok": True,
        "role": {
            "nickname": role_data.get("nickname"),
            "level": role_data.get("level"),
            "avatar_url": role_data.get("AvatarUrl") or role_data.get("game_head_icon"),
        },
        "stats": {
            "active_days": stats_data.get("active_day_number"),
            "achievements": stats_data.get("achievement_number"),
            "avatars_count": stats_data.get("avatar_number"),
            "way_points": stats_data.get("way_point_number"),
            "domains": stats_data.get("domain_number"),
            "spiral_abyss": stats_data.get("spiral_abyss"),
            "chests": {
                "common": stats_data.get("common_chest_number"),
                "exquisite": stats_data.get("exquisite_chest_number"),
                "precious": stats_data.get("precious_chest_number"),
                "luxurious": stats_data.get("luxurious_chest_number"),
                "magic": stats_data.get("magic_chest_number"),
            },
            "oculus": {
                "anemo": stats_data.get("anemoculus_number"),
                "geo": stats_data.get("geoculus_number"),
                "electro": stats_data.get("electroculus_number"),
                "dendro": stats_data.get("dendroculus_number"),
                "hydro": stats_data.get("hydroculus_number"),
                "pyro": stats_data.get("pyroculus_number"),
            },
        },
        "avatars": avatars,
    }
