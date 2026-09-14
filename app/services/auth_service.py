import json
from typing import Any, Dict, Optional
import jwt
from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one, get_connection

async def create_default_user_settings(user_id: int):
    preferences = json.dumps({
        "animations": True,
        "glass_effect": True,
        "compact_mode": False,
        "sidebar_collapsed": False,
    })
    notifications = json.dumps({
        "email": True,
        "push": True,
        "discord": False,
        "security_alert": True,
        "system_update": True,
    })
    privacy = json.dumps({
        "profile_public": False,
        "show_email": False,
        "analytics": True,
        "crash_report": True,
    })

    await execute(
        """
        INSERT IGNORE INTO user_settings 
        (user_id, theme, accent, language, timezone, developer_mode, show_api_logs, show_debug_info, preferences, notifications, privacy) 
        VALUES (%s, 'dark', 'cyan', 'vi-VN', 'Asia/Ho_Chi_Minh', false, false, false, %s, %s, %s)
        """,
        (user_id, preferences, notifications, privacy),
    )

async def handle_oauth_login_or_link(profile: Dict[str, Any], state_token: Optional[str] = None) -> Dict[str, Any]:
    current_user_id = None

    if state_token and state_token != "login":
        try:
            decoded = jwt.decode(state_token, settings.JWT_SECRET, algorithms=["HS256"])
            current_user_id = decoded.get("id")
        except Exception:
            raise ValueError("Token không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.")

    existing_oauth = await fetch_one(
        "SELECT * FROM user_oauth_accounts WHERE provider = %s AND provider_user_id = %s",
        (profile["provider"], str(profile["id"])),
    )

    # CASE 1: Account Linking
    if current_user_id:
        if existing_oauth:
            if existing_oauth["user_id"] == current_user_id:
                return {
                    "status": "success",
                    "message": f"{profile['provider']} đã được liên kết với tài khoản này từ trước.",
                    "action": "linked",
                }
            else:
                old_user = await fetch_one("SELECT * FROM users WHERE id = %s", (existing_oauth["user_id"],))
                if old_user and (
                    str(old_user.get("username", "")).startswith("discord_")
                    or not old_user.get("password_hash")
                    or old_user.get("email") == profile.get("email")
                ):
                    old_uid = old_user["id"]
                    await execute("UPDATE genshin_accounts SET user_id = %s WHERE user_id = %s", (current_user_id, old_uid))
                    await execute("UPDATE user_oauth_accounts SET user_id = %s WHERE id = %s", (current_user_id, existing_oauth["id"]))
                    await execute("DELETE FROM user_settings WHERE user_id = %s", (old_uid,))
                    await execute("DELETE FROM users WHERE id = %s", (old_uid,))
                    return {
                        "status": "success",
                        "message": f"Đã chuyển và liên kết {profile['provider']} thành công!",
                        "action": "linked",
                    }
                raise ValueError(f"Tài khoản {profile['provider']} này đã được liên kết với một người dùng khác.")

        await execute(
            """
            INSERT INTO user_oauth_accounts 
            (user_id, provider, provider_user_id, provider_email, provider_name, provider_avatar) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                current_user_id,
                profile["provider"],
                str(profile["id"]),
                profile.get("email"),
                profile.get("name"),
                profile.get("avatar"),
            ),
        )
        return {
            "status": "success",
            "message": f"Đã liên kết {profile['provider']} thành công!",
            "action": "linked",
        }

    # CASE 2: Login or Register
    if existing_oauth:
        return_user = await fetch_one("SELECT * FROM users WHERE id = %s", (existing_oauth["user_id"],))
        action_type = "login"
        await create_default_user_settings(return_user["id"])
    else:
        new_user_id = await execute(
            "INSERT INTO users (email, username, avatar) VALUES (%s, %s, %s)",
            (profile.get("email"), profile.get("name"), profile.get("avatar")),
        )
        await create_default_user_settings(new_user_id)
        await execute(
            """
            INSERT INTO user_oauth_accounts 
            (user_id, provider, provider_user_id, provider_email, provider_name, provider_avatar) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                new_user_id,
                profile["provider"],
                str(profile["id"]),
                profile.get("email"),
                profile.get("name"),
                profile.get("avatar"),
            ),
        )
        return_user = await fetch_one("SELECT * FROM users WHERE id = %s", (new_user_id,))
        action_type = "register"

    linked_providers = await fetch_all(
        "SELECT provider FROM user_oauth_accounts WHERE user_id = %s",
        (return_user["id"],),
    )
    return_user["providers"] = [p["provider"] for p in linked_providers]

    return {"status": "success", "user": return_user, "action": action_type}
