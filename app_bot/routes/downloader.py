import logging
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from app.services.downloader import downloader_service

logger = logging.getLogger("Command_Downloader")

COLOR_DEFAULT = 0x2563EB
COLOR_SUCCESS = 0x10B981
COLOR_ERROR = 0xEF4444

PLATFORM_INFO = {
    "douyin": {"name": "Douyin", "color": 0xFE2C55},
    "tiktok": {"name": "TikTok", "color": 0x00F2FE},
    "facebook": {"name": "Facebook", "color": 0x1877F2},
    "instagram": {"name": "Instagram", "color": 0xE1306C},
    "twitter": {"name": "Twitter / X", "color": 0x1DA1F2},
    "youtube": {"name": "YouTube", "color": 0xFF0000},
    "pinterest": {"name": "Pinterest", "color": 0xE60023},
    "threads": {"name": "Threads", "color": 0x101010},
    "kuaishou": {"name": "Kuaishou", "color": 0xFF5000},
    "bilibili": {"name": "Bilibili", "color": 0x00A1D6},
    "general": {"name": "Elyriax Media", "color": COLOR_DEFAULT},
}


def format_duration(seconds: float) -> str:
    """Dinh dang thoi luong video (mm:ss hoac hh:mm:ss)."""
    if not seconds or seconds <= 0:
        return "N/A"
    total_sec = int(round(seconds))
    m = total_sec // 60
    s = total_sec % 60
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def create_media_embed(data: dict, requested_by: discord.User) -> discord.Embed:
    """Tao Embed chuyen nghiep, sang trong cho ket qua downloader."""
    platform_key = (data.get("platform") or "general").lower()
    p_info = PLATFORM_INFO.get(platform_key, PLATFORM_INFO["general"])
    platform_name = p_info["name"]
    color = p_info["color"]

    is_video = bool(data.get("is_video", True))
    raw_title = data.get("title") or "Nội dung đa phương tiện"
    title = raw_title[:230] + "..." if len(raw_title) > 230 else raw_title

    embed = discord.Embed(
        title=f"[{platform_name}] {title}",
        description=f"Nội dung đã được phân tích và bóc tách link tải tốc độ cao từ máy chủ **{platform_name}**.",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Thong tin co ban
    author = data.get("author") or "Creator"
    embed.add_field(name="Tác Giả", value=f"`{author}`", inline=True)
    embed.add_field(name="Nền Tảng", value=f"`{platform_name}`", inline=True)

    if is_video:
        duration_str = format_duration(data.get("duration", 0))
        embed.add_field(name="Thời Lượng", value=f"`{duration_str}`", inline=True)
    else:
        embed.add_field(name="Định Dạng", value="`Hình ảnh tĩnh`", inline=True)

    # Thong tin cac phien ban media
    medias = data.get("medias", [])
    images = data.get("images", [])
    video_qualities = [m.get("label") or m.get("quality") for m in medias if m.get("type") == "video"]
    audio_items = [m.get("label") for m in medias if m.get("type") == "audio"]

    summary_lines = []
    if video_qualities:
        summary_lines.append(f"• **Video:** {', '.join(video_qualities[:4])}")
    if audio_items:
        summary_lines.append(f"• **Âm thanh:** {', '.join(audio_items[:3])}")
    if images or not is_video:
        count = len(images) if images else 1
        summary_lines.append(f"• **Hình ảnh:** {count} ảnh độ phân giải cao")

    if summary_lines:
        embed.add_field(name="Chất Lượng Khả Dụng", value="\n".join(summary_lines), inline=False)

    # Neu la album anh co nhieu anh, them danh sach link xem nhanh
    if len(images) > 1:
        img_links = [f"[`Ảnh {idx}`]({img_url})" for idx, img_url in enumerate(images[:6], 1)]
        embed.add_field(
            name=f"Album ({len(images)} ảnh)",
            value=" • ".join(img_links) + (f" *(+{len(images) - 6} ảnh nữa)*" if len(images) > 6 else ""),
            inline=False,
        )

    # Hien thi Preview (Cover / Thumbnail / Image)
    cover_url = data.get("cover")
    download_url = data.get("download_url")
    preview_url = download_url if (not is_video and download_url) else cover_url

    if preview_url:
        embed.set_image(url=preview_url)

    embed.set_footer(
        text=f"Elyriax Media Downloader • Yêu cầu bởi {requested_by.display_name}",
        icon_url=requested_by.display_avatar.url if requested_by.display_avatar else None,
    )
    return embed


def create_media_view(data: dict) -> discord.ui.View:
    """Tao View voi cac Button link truc tiep toi may chu Elyriax Stream."""
    view = discord.ui.View(timeout=None)
    is_video = bool(data.get("is_video", True))
    download_url = data.get("download_url")
    stream_url = data.get("stream_url")
    audio_url = data.get("audio_url")
    audio_wav_url = data.get("audio_wav_url")
    cdn_url = data.get("cdn_url")
    medias = data.get("medias", [])

    def _safe_add_btn(lbl: str, u: Optional[str], row: int):
        if u and u.startswith("http") and len(u) <= 512:
            view.add_item(discord.ui.Button(label=lbl, url=u, style=discord.ButtonStyle.link, row=row))

    # Hang 0: Cac lua chon tai chinh
    if download_url:
        btn_label = "Tải Video (MP4)" if is_video else "Tải Ảnh (HD)"
        _safe_add_btn(btn_label, download_url, row=0)

    if is_video and audio_url:
        _safe_add_btn("Tải Audio (MP3)", audio_url, row=0)

    if is_video and audio_wav_url:
        _safe_add_btn("Tải Audio (WAV)", audio_wav_url, row=0)

    if stream_url:
        lbl_stream = "Xem Trực Tuyến" if is_video else "Xem Ảnh Gốc"
        _safe_add_btn(lbl_stream, stream_url, row=0)

    # Hang 1: Cac phien ban chat luong phu / Link goc CDN
    btn_count_row1 = 0
    video_medias = [m for m in medias if m.get("type") == "video"]
    if len(video_medias) > 1:
        for vm in video_medias[1:4]:
            q_label = vm.get("label") or vm.get("quality") or "Video"
            q_url = vm.get("download_url")
            if q_url and btn_count_row1 < 3:
                _safe_add_btn(f"Bản {q_label}", q_url, row=1)
                btn_count_row1 += 1

    if cdn_url and btn_count_row1 < 4:
        _safe_add_btn("Link Gốc (CDN)", cdn_url, row=1)

    return view


def create_error_embed(error_msg: str, url: str) -> discord.Embed:
    """Embed bao loi ro rang, lich su."""
    embed = discord.Embed(
        title="Không Thể Bóc Tách Liên Kết",
        description=f"Hệ thống không thể tải nội dung từ đường dẫn được cung cấp.\n\n**Chi tiết:** `{error_msg}`",
        color=COLOR_ERROR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Đường Dẫn Đã Gửi",
        value=f"`{url[:200]}`" if len(url) <= 200 else f"`{url[:197]}...`",
        inline=False,
    )
    embed.add_field(
        name="Hướng Dẫn Kiểm Tra",
        value=(
            "• Đảm bảo bài viết/video ở chế độ công khai (Public).\n"
            "• Kiểm tra liên kết có thể mở được bình thường trên trình duyệt hay không.\n"
            "• Hỗ trợ: **Douyin, TikTok, Facebook, Instagram, Twitter/X, YouTube, Pinterest, Threads, Bilibili**."
        ),
        inline=False,
    )
    embed.set_footer(text="Elyriax Media Downloader")
    return embed


class DownloaderCog(commands.Cog, name="Downloader"):
    """Cog quan ly cac lenh tai video va hinh anh da nen tang."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dang ky Context Menu Command (chuot phai vao tin nhan)
        self.context_menu = app_commands.ContextMenu(
            name="Tải Media Downloader",
            callback=self.context_download_media,
        )
        self.bot.tree.add_command(self.context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.context_menu.name, type=self.context_menu.type)

    async def _handle_download_request(
        self,
        interaction_or_ctx,
        raw_input: str,
        is_interaction: bool = True,
    ):
        """Xu ly chung logic bóc tách va tra ve Embed + View."""
        # Defer phan hoi truoc vi goi API ben ngoai co the mat 1-3 giay
        if is_interaction:
            await interaction_or_ctx.response.defer(thinking=True)
            user = interaction_or_ctx.user
        else:
            user = interaction_or_ctx.author

        try:
            target_url = downloader_service.clean_url(raw_input)
            data = await downloader_service.extract_info(target_url)

            embed = create_media_embed(data, requested_by=user)
            view = create_media_view(data)

            if is_interaction:
                await interaction_or_ctx.followup.send(embed=embed, view=view)
            else:
                await interaction_or_ctx.reply(embed=embed, view=view, mention_author=False)

        except Exception as e:
            logger.warning(f"Downloader error for input '{raw_input}': {e}")
            error_embed = create_error_embed(str(e), raw_input)
            if is_interaction:
                await interaction_or_ctx.followup.send(embed=error_embed)
            else:
                await interaction_or_ctx.reply(embed=error_embed, mention_author=False)

    # ----------------------------------------------------
    # /download [url]
    # ----------------------------------------------------
    @app_commands.command(
        name="download",
        description="Tải video, hình ảnh và âm thanh từ Douyin, TikTok, Facebook, Instagram, Pinterest...",
    )
    @app_commands.describe(url="Đường dẫn hoặc đoạn văn bản chia sẻ chứa link video/ảnh")
    async def download_command(self, interaction: discord.Interaction, url: str):
        await self._handle_download_request(interaction, url, is_interaction=True)

    # ----------------------------------------------------
    # /douyin [url]
    # ----------------------------------------------------
    @app_commands.command(
        name="douyin",
        description="Tải video, ảnh và nhạc nền Douyin không logo tốc độ cao",
    )
    @app_commands.describe(url="Link chia sẻ video hoặc album ảnh Douyin")
    async def douyin_command(self, interaction: discord.Interaction, url: str):
        await self._handle_download_request(interaction, url, is_interaction=True)

    # ----------------------------------------------------
    # /tiktok [url]
    # ----------------------------------------------------
    @app_commands.command(
        name="tiktok",
        description="Tải video TikTok không logo và tự động trích xuất âm thanh MP3/WAV",
    )
    @app_commands.describe(url="Link chia sẻ video TikTok (vt.tiktok.com, tiktok.com/@...)")
    async def tiktok_command(self, interaction: discord.Interaction, url: str):
        await self._handle_download_request(interaction, url, is_interaction=True)

    # ----------------------------------------------------
    # /pinterest [url]
    # ----------------------------------------------------
    @app_commands.command(
        name="pinterest",
        description="Tải ảnh và video chất lượng gốc từ Pinterest",
    )
    @app_commands.describe(url="Link ghim Pinterest (pin.it, pinterest.com/pin/...)")
    async def pinterest_command(self, interaction: discord.Interaction, url: str):
        await self._handle_download_request(interaction, url, is_interaction=True)

    # ----------------------------------------------------
    # Context Menu: Tải Media Downloader
    # ----------------------------------------------------
    async def context_download_media(self, interaction: discord.Interaction, message: discord.Message):
        content = message.content or ""
        match = re.search(r"https?://[^\s\"'<>]+", content)
        if not match:
            await interaction.response.send_message(
                "Tin nhắn này không chứa đường dẫn URL hợp lệ để tải media.",
                ephemeral=True,
            )
            return

        target_url = match.group(0)
        await self._handle_download_request(interaction, target_url, is_interaction=True)

    # ----------------------------------------------------
    # Prefix command: !download, !dl, !tai
    # ----------------------------------------------------
    @commands.command(name="download", aliases=["dl", "tai", "get"])
    async def prefix_download(self, ctx: commands.Context, *, url: str):
        """Lệnh văn bản tải video/ảnh nhanh: !dl <url>"""
        await self._handle_download_request(ctx, url, is_interaction=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(DownloaderCog(bot))

