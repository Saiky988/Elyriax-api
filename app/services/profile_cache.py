import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import httpx
from app.core.config import settings

logger = logging.getLogger("ProfileCache")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
PROFILE_DIR = DATA_DIR / "profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_FILE_PATH = DATA_DIR / "token_user.json"

tracked_users: Set[str] = set()
tokens: List[str] = []
current_token_index = 0

def load_tokens():
    global tokens
    if TOKEN_FILE_PATH.exists():
        try:
            with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f:
                tokens = json.load(f)
                logger.info(f"[Token System] Đã tải {len(tokens)} token từ token_user.json")
        except Exception as err:
            logger.error(f"[Token System] Lỗi khi đọc token_user.json: {err}")

    if not tokens and settings.USER_TOKEN:
        tokens.append(settings.USER_TOKEN)
        logger.info("[Token System] Sử dụng USER_TOKEN từ biến môi trường làm fallback.")

load_tokens()

def get_next_token() -> Optional[str]:
    global current_token_index, tokens
    if not tokens:
        return None
    token = tokens[current_token_index]
    current_token_index = (current_token_index + 1) % len(tokens)
    return token

def get_avatar(user: Dict[str, Any]) -> str:
    user_id = str(user.get("id"))
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=512"
    try:
        idx = int(user_id) % 5
    except Exception:
        idx = 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"

def get_banner(user: Dict[str, Any]) -> Optional[str]:
    user_id = str(user.get("id"))
    banner = user.get("banner")
    if not banner:
        return None
    ext = "gif" if banner.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/banners/{user_id}/{banner}.{ext}?size=1024"

def parse_clan_data(clan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not clan or not clan.get("identity_guild_id") or not clan.get("badge"):
        return clan
    res = dict(clan)
    res["badge_url"] = f"https://cdn.discordapp.com/clan-badges/{clan['identity_guild_id']}/{clan['badge']}.png?size=128"
    return res

def parse_badges(badges: Any) -> List[Dict[str, Any]]:
    if not isinstance(badges, list):
        return []
    res = []
    for b in badges:
        item = dict(b)
        if item.get("icon"):
            item["url"] = f"https://cdn.discordapp.com/badge-icons/{item['icon']}.png?size=96"
        res.append(item)
    return res

def parse_collectibles(collectibles: Any, user_profile: Dict[str, Any]) -> Dict[str, Any]:
    data = {
        "nameplate": (collectibles or {}).get("nameplate"),
        "profile_effect": user_profile.get("profile_effect"),
        "all_collectibles": user_profile.get("collectibles", []),
    }
    if data["nameplate"] and data["nameplate"].get("sku_id"):
        data["nameplate"]["url"] = f"https://cdn.discordapp.com/avatar-decoration-presets/nameplates/{data['nameplate']['sku_id']}.png?size=240"
    if data["profile_effect"] and data["profile_effect"].get("sku_id"):
        data["profile_effect"]["url"] = f"https://cdn.discordapp.com/assets/profile-effects/{data['profile_effect']['sku_id']}.png"
    return data

def translate_status(status_str: str, lang: str = "vi") -> str:
    mapping = {
        "vi": {"online": "Đang trực tuyến", "idle": "Đang trực tuyến", "dnd": "Đang trực tuyến", "offline": "Ngoại tuyến"},
        "en": {"online": "Online", "idle": "Online", "dnd": "Online", "offline": "Offline"},
    }
    return mapping.get(lang, {}).get(status_str, status_str)

async def fetch_profile(user_id: str) -> Optional[Dict[str, Any]]:
    global tokens, current_token_index
    current_token = get_next_token()
    if not current_token:
        logger.warning("Missing Discord USER_TOKEN for profile cache")
        return None

    try:
        url = f"https://discord.com/api/v10/users/{user_id}/profile?with_mutual_guilds=false&with_mutual_friends_count=false"
        headers = {
            "Authorization": current_token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Discord-Locale": "en-US",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url, headers=headers)

        if res.status_code == 401:
            logger.warning(f"[Token System] Token báo 401: {current_token[:10]}...")
            tokens = [t for t in tokens if t != current_token]
            if current_token_index >= len(tokens):
                current_token_index = 0
            return None

        user_profile_data = res.json()
        user = user_profile_data.get("user")
        if not user:
            return None

        user_profile = user_profile_data.get("user_profile") or {}
        avatar_decoration_url = None
        if user.get("avatar_decoration_data"):
            avatar_decoration_url = f"https://cdn.discordapp.com/avatar-decoration-presets/{user['avatar_decoration_data'].get('asset')}.png?size=240"

        presence_status = user_profile_data.get("presence", {}).get("status", "offline")
        now_ms = int(time.time() * 1000)

        file_path = PROFILE_DIR / f"{user_id}.json"
        existing = {}
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        last_online = existing.get("data", {}).get("presence", {}).get("last_online", now_ms)
        if presence_status != "offline":
            last_online = now_ms

        profile_data = {
            "success": True,
            "updated_at": now_ms,
            "data": {
                "id": user.get("id"),
                "username": user.get("username"),
                "global_name": user.get("global_name") or user.get("username"),
                "avatar": get_avatar(user),
                "banner": get_banner(user),
                "avatar_decoration": avatar_decoration_url,
                "banner_color": user.get("banner_color") or "#000000",
                "accent_color": user.get("accent_color") or user_profile.get("accent_color"),
                "pronouns": user_profile.get("pronouns", ""),
                "about_me": user_profile.get("bio") or user.get("bio") or "Không có tiểu sử.",
                "clan": parse_clan_data(user.get("clan") or user.get("primary_guild")),
                "collectibles": parse_collectibles(user.get("collectibles"), user_profile),
                "badges": parse_badges(user_profile_data.get("badges")),
                "guild_badges": parse_badges(user_profile_data.get("guild_badges")),
                "premium": {
                    "type": user_profile_data.get("premium_type", 0),
                    "since": user_profile_data.get("premium_since"),
                    "guild_since": user_profile_data.get("premium_guild_since"),
                },
                "connected_accounts": user_profile_data.get("connected_accounts", []),
                "server_nickname": user_profile_data.get("guild_member", {}).get("nick"),
                "server_tags": [],
                "widgets": user_profile_data.get("widgets", []),
                "wishlist_settings": user_profile_data.get("wishlist_settings", {}),
                "presence": {
                    "status": presence_status,
                    "status_text_vi": translate_status(presence_status, "vi"),
                    "status_text_en": translate_status(presence_status, "en"),
                    "online": presence_status in ["online", "idle", "dnd"],
                    "custom_status": None,
                    "activities": [],
                    "last_online": last_online,
                },
            },
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)

        return profile_data
    except Exception as e:
        logger.error(f"[CACHE ERROR] {user_id}: {e}")
        return None

def track_user(user_id: str):
    tracked_users.add(str(user_id))

async def profile_cache_loop():
    while True:
        try:
            for u_id in list(tracked_users):
                await fetch_profile(u_id)
                await asyncio.sleep(1.5)
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[ProfileCache Worker Error]: {e}")
            await asyncio.sleep(10.0)

def start_profile_cache() -> asyncio.Task:
    return asyncio.create_task(profile_cache_loop())
