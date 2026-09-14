import json
from typing import Any, Dict, Optional
from app.core.database import execute, fetch_one

DEFAULT_PREFERENCES = {"animations": True, "glass_effect": True, "compact_mode": False, "sidebar_collapsed": False}
DEFAULT_NOTIFICATIONS = {"email": True, "push": True, "discord": False, "security_alert": False, "system_update": False}
DEFAULT_PRIVACY = {"profile_public": False, "show_email": False, "analytics": True, "crash_report": True}

def safe_parse(val: Any, default_val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default_val
    return val or default_val

def format_settings(row: Dict[str, Any]) -> Dict[str, Any]:
    res = dict(row)
    res["preferences"] = safe_parse(res.get("preferences"), DEFAULT_PREFERENCES)
    res["notifications"] = safe_parse(res.get("notifications"), DEFAULT_NOTIFICATIONS)
    res["privacy"] = safe_parse(res.get("privacy"), DEFAULT_PRIVACY)
    return res

async def get_settings(user_id: int) -> Dict[str, Any]:
    row = await fetch_one(
        """
        SELECT theme, accent, language, timezone, developer_mode, show_api_logs, show_debug_info, 
               preferences, notifications, privacy 
        FROM user_settings WHERE user_id = %s
        """,
        (user_id,),
    )
    if row:
        return format_settings(row)

    await execute(
        """
        INSERT IGNORE INTO user_settings 
        (user_id, theme, accent, language, timezone, developer_mode, show_api_logs, show_debug_info, preferences, notifications, privacy) 
        VALUES (%s, 'dark', 'cyan', 'vi-VN', 'Asia/Ho_Chi_Minh', false, false, false, %s, %s, %s)
        """,
        (user_id, json.dumps(DEFAULT_PREFERENCES), json.dumps(DEFAULT_NOTIFICATIONS), json.dumps(DEFAULT_PRIVACY)),
    )

    row = await fetch_one(
        """
        SELECT theme, accent, language, timezone, developer_mode, show_api_logs, show_debug_info, 
               preferences, notifications, privacy 
        FROM user_settings WHERE user_id = %s
        """,
        (user_id,),
    )
    return format_settings(row)

async def update_settings(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    current_settings = await get_settings(user_id)
    updates = []
    values = []

    if "theme" in data:
        if data["theme"] not in ["dark", "light", "system", "classic_dark"]:
            raise ValueError("Theme không hợp lệ")
        updates.append("theme = %s")
        values.append(data["theme"])

    if "accent" in data:
        if data["accent"] not in ["cyan", "blue", "purple", "pink", "red", "amber"]:
            raise ValueError("Accent không hợp lệ")
        updates.append("accent = %s")
        values.append(data["accent"])

    if "language" in data:
        if data["language"] not in ["vi-VN", "en-US"]:
            raise ValueError("Ngôn ngữ không hợp lệ")
        updates.append("language = %s")
        values.append(data["language"])

    if "timezone" in data:
        if not isinstance(data["timezone"], str) or len(data["timezone"]) > 50:
            raise ValueError("Timezone không hợp lệ (tối đa 50 ký tự)")
        updates.append("timezone = %s")
        values.append(data["timezone"])

    if "developer_mode" in data:
        updates.append("developer_mode = %s")
        values.append(bool(data["developer_mode"]))

    if "show_api_logs" in data:
        updates.append("show_api_logs = %s")
        values.append(bool(data["show_api_logs"]))

    if "show_debug_info" in data:
        updates.append("show_debug_info = %s")
        values.append(bool(data["show_debug_info"]))

    if "preferences" in data and isinstance(data["preferences"], dict):
        merged = {**current_settings.get("preferences", DEFAULT_PREFERENCES), **data["preferences"]}
        updates.append("preferences = %s")
        values.append(json.dumps(merged))

    if "notifications" in data and isinstance(data["notifications"], dict):
        merged = {**current_settings.get("notifications", DEFAULT_NOTIFICATIONS), **data["notifications"]}
        updates.append("notifications = %s")
        values.append(json.dumps(merged))

    if "privacy" in data and isinstance(data["privacy"], dict):
        merged = {**current_settings.get("privacy", DEFAULT_PRIVACY), **data["privacy"]}
        updates.append("privacy = %s")
        values.append(json.dumps(merged))

    if not updates:
        return current_settings

    values.append(user_id)
    sql = f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = %s"
    await execute(sql, tuple(values))

    return await get_settings(user_id)
