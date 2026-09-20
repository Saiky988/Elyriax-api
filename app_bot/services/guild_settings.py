import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import discord

logger = logging.getLogger("GuildSettings")

# Path tới file cấu hình guild
SETTINGS_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = SETTINGS_DIR / "guild_settings.json"

_SETTINGS_CACHE: Dict[str, Dict[str, Any]] = {}

DEFAULT_GUILD_CONFIG: Dict[str, Any] = {
    # Welcome Configuration
    "welcome_enabled": False,
    "welcome_channel_id": None,
    "welcome_message": "Chào mừng {user} đã gia nhập **{server}**! Bạn là thành viên thứ **#{member_count}**.",
    "welcome_embed": True,
    "welcome_title": "THÀNH VIÊN MỚI GIA NHẬP",
    "welcome_color": 0x10B981,  # Emerald Green

    # Leave Configuration
    "leave_enabled": False,
    "leave_channel_id": None,
    "leave_message": "Tạm biệt **{user_name}** đã rời khỏi **{server}**. Hẹn gặp lại bạn!",
    "leave_embed": True,
    "leave_title": "THÀNH VIÊN RỜI MÁY CHỦ",
    "leave_color": 0xEF4444,  # Red

    # Auto Role Configuration
    "autorole_enabled": False,
    "autorole_id": None,

    "updated_at": None,
}


def load_all_settings() -> Dict[str, Dict[str, Any]]:
    global _SETTINGS_CACHE
    if not SETTINGS_FILE.exists():
        _SETTINGS_CACHE = {}
        return _SETTINGS_CACHE

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            _SETTINGS_CACHE = json.load(f)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file guild_settings.json: {e}")
        _SETTINGS_CACHE = {}

    return _SETTINGS_CACHE


def save_all_settings(data: Dict[str, Dict[str, Any]]):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Lỗi khi ghi file guild_settings.json: {e}")


def get_guild_settings(guild_id: int) -> Dict[str, Any]:
    global _SETTINGS_CACHE
    if not _SETTINGS_CACHE:
        load_all_settings()

    gid_str = str(guild_id)
    if gid_str not in _SETTINGS_CACHE:
        _SETTINGS_CACHE[gid_str] = dict(DEFAULT_GUILD_CONFIG)
    else:
        # Đảm bảo có đầy đủ các key mới nếu cấu trúc được cập nhật
        for k, v in DEFAULT_GUILD_CONFIG.items():
            if k not in _SETTINGS_CACHE[gid_str]:
                _SETTINGS_CACHE[gid_str][k] = v

    return _SETTINGS_CACHE[gid_str]


def update_guild_settings(guild_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    current = get_guild_settings(guild_id)
    current.update(updates)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SETTINGS_CACHE[str(guild_id)] = current
    save_all_settings(_SETTINGS_CACHE)
    return current


def format_placeholders(template: str, member: discord.Member, guild: discord.Guild) -> str:
    """Thay thế các biến động trong nội dung tin nhắn."""
    if not template:
        return ""

    created_str = member.created_at.strftime("%d/%m/%Y") if member.created_at else "N/A"
    joined_str = member.joined_at.strftime("%d/%m/%Y") if getattr(member, "joined_at", None) else "N/A"

    replacements = {
        "{user}": member.mention,
        "{user_name}": member.display_name,
        "{user_tag}": member.name,
        "{user_id}": str(member.id),
        "{server}": guild.name,
        "{server_id}": str(guild.id),
        "{member_count}": str(guild.member_count or 0),
        "{created_at}": created_str,
        "{joined_at}": joined_str,
    }

    result = template
    for placeholder, val in replacements.items():
        result = result.replace(placeholder, val)
    return result


def build_welcome_embed(member: discord.Member, config: Dict[str, Any]) -> discord.Embed:
    guild = member.guild
    title = config.get("welcome_title") or "THÀNH VIÊN MỚI GIA NHẬP"
    color = config.get("welcome_color") or 0x10B981
    raw_desc = config.get("welcome_message") or "Chào mừng {user} đã gia nhập **{server}**!"
    desc = format_placeholders(raw_desc, member, guild)

    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Avatar dạng Thumbnail nhỏ gọn ở góc trên bên phải
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    created_str = member.created_at.strftime("%d/%m/%Y %H:%M") if member.created_at else "N/A"
    embed.add_field(
        name="Thông Tin Tài Khoản",
        value=f"• **Username:** `{member.name}`\n• **ID:** `{member.id}`\n• **Ngày tạo:** `{created_str}`",
        inline=True,
    )
    embed.add_field(
        name="Thành Viên",
        value=f"• **Vị trí:** `#{guild.member_count}`\n• **Máy chủ:** `{guild.name}`",
        inline=True,
    )

    embed.set_footer(
        text=f"{guild.name} • Hệ thống chào mừng tự động",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return embed


def build_leave_embed(member: discord.Member, config: Dict[str, Any]) -> discord.Embed:
    guild = member.guild
    title = config.get("leave_title") or "THÀNH VIÊN RỜI MÁY CHỦ"
    color = config.get("leave_color") or 0xEF4444
    raw_desc = config.get("leave_message") or "Tạm biệt **{user_name}** đã rời khỏi **{server}**. Hẹn gặp lại bạn!"
    desc = format_placeholders(raw_desc, member, guild)

    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    joined_str = member.joined_at.strftime("%d/%m/%Y %H:%M") if getattr(member, "joined_at", None) else "N/A"
    embed.add_field(
        name="Thông Tin",
        value=f"• **Username:** `{member.name}`\n• **ID:** `{member.id}`\n• **Tham gia lúc:** `{joined_str}`",
        inline=True,
    )
    embed.add_field(
        name="Hiện Còn",
        value=f"• **Số lượng:** `{guild.member_count} thành viên`",
        inline=True,
    )

    embed.set_footer(
        text=f"{guild.name} • Thông báo rời máy chủ",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return embed
