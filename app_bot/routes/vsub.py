import logging
import os
import re
import shutil
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from app.services.downloader import downloader_service
from app_bot.services.pipeline import bot_pipeline

logger = logging.getLogger("Command_Subtitles")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB Limit


def format_bytes(size: int) -> str:
    power = 1024
    n = 0
    labels = {0: "B", 1: "KB", 2: "MB", 3: "GB"}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {labels.get(n, 'MB')}"


def format_duration(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def create_process_embed(filename: str, file_size: int, stage_desc: str, translate: bool = True) -> discord.Embed:
    title = "PIPELINE SYNTHESIS IN PROGRESS" if translate else "SUBTITLE EXTRACTION IN PROGRESS"
    desc = (
        "Hệ thống đang điều phối tài nguyên và xử lý pipeline phụ đề tự động..."
        if translate
        else "Hệ thống đang trích xuất giọng nói và bóc tách phụ đề gốc..."
    )
    embed = discord.Embed(
        title=f"<:50919aseprite:1548611674418847814> {title}",
        description=desc,
        color=0x38BDF8,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Target Media",
        value=f"```fix\nName: {filename}\nSize: {format_bytes(file_size)}\nStatus: Active Processing\n```",
        inline=False,
    )

    if translate:
        stages = (
            f"**Current Task:** `{stage_desc}`\n"
            "• **Stage 1:** FFmpeg Audio Demuxing `[16kHz Mono]`\n"
            "• **Stage 2:** OpenAI Whisper Large-v3\n"
            "• **Stage 3:** Google Gemini 3.5 Flash-Lite\n"
            "• **Stage 4:** Assembly & SRT Packaging"
        )
    else:
        stages = (
            f"**Current Task:** `{stage_desc}`\n"
            "• **Stage 1:** FFmpeg Audio Demuxing `[16kHz Mono]`\n"
            "• **Stage 2:** OpenAI Whisper Large-v3 (Speech-to-Text)\n"
            "• **Stage 3:** Assembly & Raw SRT Packaging"
        )

    embed.add_field(name="Pipeline Execution Stages", value=stages, inline=False)
    embed.add_field(name="Node Allocation", value="`Cluster:` **Ryzen 9 7900**", inline=False)
    embed.set_footer(text="Tiến trình đang chạy..")
    return embed


async def download_remote_media(url: str) -> Tuple[bytes, str]:
    """
    Tải media từ URL từ xa với hỗ trợ thông minh:
    - Google Drive (tự động chuyển đổi thành direct download URL)
    - Mạng xã hội / Video platforms (TikTok, YouTube, Douyin, Facebook... qua downloader_service)
    - Direct HTTP/HTTPS media URL
    """
    url = url.strip()

    # 1. Phát hiện & chuyển đổi Google Drive URL
    gd_match = re.search(
        r"(?:drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^&]+&)*id=)|drive\.usercontent\.google\.com/download\?id=)([a-zA-Z0-9_-]{20,})",
        url,
    )
    is_google_drive = bool(gd_match)

    if is_google_drive:
        file_id = gd_match.group(1)
        target_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    else:
        # 2. Phát hiện nền tảng video (YouTube, TikTok, Facebook...)
        platform = downloader_service.detect_platform(url)
        if platform != "general":
            try:
                parsed = await downloader_service.parse_media(url)
                target_url = (
                    parsed.get("stream_url")
                    or parsed.get("download_url")
                    or parsed.get("audio_url")
                    or url
                )
            except Exception:
                target_url = url
        else:
            target_url = url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=180.0) as client:
        async with client.stream("GET", target_url) as response:
            if response.status_code != 200:
                raise ValueError(f"Không thể tải media từ URL (HTTP Status: {response.status_code}).")

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                if is_google_drive:
                    raise ValueError(
                        "Liên kết Google Drive không công khai hoặc bị giới hạn quyền truy cập. "
                        "Vui lòng bật chế độ 'Bất kỳ ai có đường liên kết đều có thể xem' (Public Link)."
                    )
                raise ValueError("URL trỏ về trang web HTML thay vì tệp video/audio thực tế. Vui lòng kiểm tra lại liên kết.")

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"Dung lượng tệp ({format_bytes(int(content_length))}) vượt quá giới hạn cho phép ({format_bytes(MAX_FILE_SIZE_BYTES)})."
                )

            # Xác định filename chuẩn từ Content-Disposition
            filename = None
            cd = response.headers.get("Content-Disposition", "")
            if cd:
                fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)["\']?', cd, re.IGNORECASE)
                if fname_match:
                    filename = urllib.parse.unquote(fname_match.group(1).strip())

            # Fallback lấy filename từ URL path
            if not filename:
                parsed_path = urllib.parse.urlparse(target_url).path
                base = os.path.basename(parsed_path)
                if base and any(base.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
                    filename = base
                else:
                    filename = "remote_media.mp4"

            # Đảm bảo đuôi mở rộng hợp lệ
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                filename = f"{os.path.splitext(filename)[0]}.mp4"

            # Đọc chunks và kiểm tra dung lượng
            chunks = []
            total_read = 0
            async for chunk in response.aiter_bytes(chunk_size=128 * 1024):
                total_read += len(chunk)
                if total_read > MAX_FILE_SIZE_BYTES:
                    raise ValueError(
                        f"Dung lượng stream vượt quá ngưỡng tối đa ({format_bytes(MAX_FILE_SIZE_BYTES)})."
                    )
                chunks.append(chunk)

            file_bytes = b"".join(chunks)
            return file_bytes, filename


async def run_pipeline(
    interaction: discord.Interaction,
    file_bytes: bytes,
    filename: str,
    start_time: float,
    translate: bool = True,
):
    temp_dir_path = None
    try:
        stage_desc = "Demuxing Audio & Generating Vietsub..." if translate else "Demuxing Audio & Extracting SRT..."
        process_embed = create_process_embed(
            filename=filename,
            file_size=len(file_bytes),
            stage_desc=stage_desc,
            translate=translate,
        )
        await interaction.edit_original_response(embed=process_embed)

        # Thực thi pipeline AI
        metrics = await bot_pipeline.process_file_to_srt(
            file_bytes=file_bytes,
            filename=filename,
            translate=translate,
        )
        temp_dir_path = metrics.temp_dir
        execution_time = time.perf_counter() - start_time

        # Khởi tạo Success Embed
        if translate:
            title = "VIETSUB COMPLETED"
            desc = "Tiến trình bóc tách phụ đề và chuyển ngữ ngữ cảnh hoàn tất. File `.srt` đã được đóng gói sẵn sàng xuất bản."
            embed_color = 0x00FFA3
        else:
            title = "SUBTITLES EXTRACTED (.SRT)"
            desc = "Tiến trình bóc tách phụ đề gốc (không dịch) hoàn tất. File `.srt` đã được đóng gói sẵn sàng xuất bản."
            embed_color = 0x6366F1

        success_embed = discord.Embed(
            title=f"<:50919aseprite:1548611674418847814> {title}",
            description=desc,
            color=embed_color,
            timestamp=datetime.now(timezone.utc),
        )

        success_embed.add_field(
            name="<:50919aseprite:1548611674418847814> Source Media",
            value=f"```fix\nName: {filename}\nSize: {format_bytes(len(file_bytes))}\nLength: {format_duration(metrics.audio_duration)}\n```",
            inline=False,
        )

        inference_ratio = metrics.audio_duration / max(0.1, execution_time)
        telemetry_info = (
            f"• **Segments Created:** `{metrics.segment_count}` khối phụ đề\n"
            f"• **Source Language:** `{metrics.detected_language}`\n"
            f"• **Processing Latency:** `{execution_time:.2f}s`\n"
            f"• **Throughput Speed:** `{inference_ratio:.1f}x realtime`"
        )
        success_embed.add_field(name="Telemetry & Benchmark", value=telemetry_info, inline=False)

        if translate:
            arch_info = (
                "`STT Engine:` **OpenAI Whisper Large-v3**\n"
                "`LLM Engine:` **Google Gemini 3.5 Flash-Lite**\n"
                "`Node Cluster:` **Ryzen 9 7900**"
            )
        else:
            arch_info = (
                "`STT Engine:` **OpenAI Whisper Large-v3**\n"
                "`Processing Mode:` **Native Audio Transcription (No Translation)**\n"
                "`Node Cluster:` **Ryzen 9 7900**"
            )
        success_embed.add_field(name="Computational Stack", value=arch_info, inline=False)

        footer_label = "Vietsub Studio Enterprise" if translate else "Subtitle Extractor Engine"
        success_embed.set_footer(
            text=f"{footer_label} • Session ID: {interaction.id}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        )

        discord_file = discord.File(str(metrics.srt_path), filename=metrics.srt_path.name)
        await interaction.edit_original_response(embed=success_embed, attachments=[discord_file])

    except Exception as e:
        cmd_name = "/vsub" if translate else "/srt"
        logger.error(f"Lỗi thực thi pipeline {cmd_name}: {str(e)}", exc_info=True)
        elapsed = time.perf_counter() - start_time

        fail_embed = discord.Embed(
            title="<:685108warn:1548610613528494121> PIPELINE EXECUTION FAILED",
            description="Đã xảy ra sự cố trong quá trình xử lý pipeline tự động.",
            color=0xFF3366,
            timestamp=datetime.now(timezone.utc),
        )
        fail_embed.add_field(
            name="Error Diagnostics",
            value=f"```py\n{type(e).__name__}: {str(e)[:400]}\n```",
            inline=False,
        )
        fail_embed.add_field(
            name="Execution Metrics",
            value=f"• **Elapsed Before Crash:** `{elapsed:.2f}s`\n• **File Name:** `{filename}`",
            inline=False,
        )
        fail_embed.set_footer(text="Hệ thống đã tự động ghi nhận crash log.")
        await interaction.edit_original_response(embed=fail_embed, attachments=[])

    finally:
        if temp_dir_path and os.path.exists(temp_dir_path):
            shutil.rmtree(temp_dir_path, ignore_errors=True)


class MediaURLModal(discord.ui.Modal):
    def __init__(self, translate: bool = True):
        title = "Vietsub Studio (Dịch Tiếng Việt)" if translate else "Subtitle Extractor (SRT Gốc)"
        super().__init__(title=title)
        self.translate = translate

    media_url = discord.ui.TextInput(
        label="Media URL",
        placeholder="Link Google Drive, YouTube, TikTok, hoặc URL video trực tiếp...",
        style=discord.TextStyle.short,
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw_url = self.media_url.value.strip()

        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()

        # Hiển thị embed Ingestion
        downloading_embed = discord.Embed(
            title="<a:chiikawascuba:1548601830140022825> INGESTING REMOTE STREAM",
            description="Đang kết nối đến máy chủ nguồn để truyền tải payload dữ liệu...",
            color=0xF59E0B,
            timestamp=datetime.now(timezone.utc),
        )
        downloading_embed.add_field(
            name="Stream URL",
            value=f"```fix\n{raw_url[:120]}...\n```" if len(raw_url) > 120 else f"```fix\n{raw_url}\n```",
            inline=False,
        )
        await interaction.edit_original_response(embed=downloading_embed)

        try:
            file_bytes, filename = await download_remote_media(raw_url)
        except Exception as err:
            logger.error(f"Lỗi tải URL: {str(err)}", exc_info=True)
            error_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> URL Connection Error",
                description=f"Không thể kết nối tải tệp nguồn:\n`{str(err)[:300]}`",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc),
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        await run_pipeline(interaction, file_bytes, filename, start_time, translate=self.translate)


class SubtitlesCog(commands.Cog, name="Subtitles"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="vsub",
        description="Tự động bóc tách phụ đề và dịch Vietsub sang tiếng Việt"
    )
    @app_commands.describe(
        file="Tệp Media (Video/Audio). Để trống tùy chọn này để mở Modal nhập URL"
    )
    async def vsub(self, interaction: discord.Interaction, file: Optional[discord.Attachment] = None):
        """Lệnh /vsub: Bóc tách phụ đề và dịch sang tiếng Việt."""
        if file is None:
            await interaction.response.send_modal(MediaURLModal(translate=True))
            return

        await self._handle_attachment(interaction, file, translate=True)

    @app_commands.command(
        name="srt",
        description="Tự động bóc tách phụ đề gốc (.srt) từ video/audio (Không dịch)"
    )
    @app_commands.describe(
        file="Tệp Media (Video/Audio). Để trống tùy chọn này để mở Modal nhập URL"
    )
    async def srt(self, interaction: discord.Interaction, file: Optional[discord.Attachment] = None):
        """Lệnh /srt: Bóc tách phụ đề gốc, không dịch sang tiếng Việt."""
        if file is None:
            await interaction.response.send_modal(MediaURLModal(translate=False))
            return

        await self._handle_attachment(interaction, file, translate=False)

    async def _handle_attachment(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        translate: bool = True,
    ):
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in ALLOWED_EXTENSIONS:
            error_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> Invalid Media Format",
                description=f"Hệ thống không chấp nhận định dạng `{file_ext}`.",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc),
            )
            error_embed.add_field(
                name="Hỗ trợ chuẩn",
                value="`mp4`, `mov`, `mkv`, `webm`, `mp3`, `wav`, `m4a`",
                inline=False,
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return

        if file.size > MAX_FILE_SIZE_BYTES:
            size_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> Payload Entity Too Large",
                description=f"Dung lượng tệp ({format_bytes(file.size)}) vượt quá ngưỡng tối đa cho phép ({format_bytes(MAX_FILE_SIZE_BYTES)}).",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc),
            )
            await interaction.response.send_message(embed=size_embed, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()

        initial_embed = create_process_embed(
            filename=file.filename,
            file_size=file.size,
            stage_desc="Reading payload bytes...",
            translate=translate,
        )
        await interaction.edit_original_response(embed=initial_embed)

        file_bytes = await file.read()
        await run_pipeline(interaction, file_bytes, file.filename, start_time, translate=translate)


async def setup(bot: commands.Bot):
    await bot.add_cog(SubtitlesCog(bot))