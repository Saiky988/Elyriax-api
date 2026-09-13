import os
import shutil
import time
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from app_bot.services.pipeline import bot_pipeline

logger = logging.getLogger("Command_Vsub")

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


def create_process_embed(filename: str, file_size: int, stage_desc: str) -> discord.Embed:
    embed = discord.Embed(
        title="<:50919aseprite:1548611674418847814> PIPELINE SYNTHESIS IN PROGRESS",
        description="Hệ thống đang điều phối tài nguyên và xử lý pipeline phụ đề tự động...",
        color=0x38BDF8,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name="Target Media",
        value=f"```fix\nName: {filename}\nSize: {format_bytes(file_size)}\nStatus: Active Processing\n```",
        inline=False
    )
    embed.add_field(
        name="Pipeline Execution Stages",
        value=(
            f"**Current Task:** `{stage_desc}`\n"
            "• **Stage 1:** FFmpeg Audio Demuxing `[16kHz Mono]`\n"
            "• **Stage 2:** OpenAI Whisper Large-v3\n"
            "• **Stage 3:** Google Gemini 3.5 Flash-Lite\n"
            "• **Stage 4:** Assembly & SRT Packaging"
        ),
        inline=False
    )
    embed.add_field(
        name="Node Allocation",
        value="`Cluster:` **Ryzen 9 7900**",
        inline=False
    )
    embed.set_footer(text="Tiến trình đang chạy..")
    return embed


async def run_pipeline(
    interaction: discord.Interaction,
    file_bytes: bytes,
    filename: str,
    start_time: float
):
    temp_dir_path = None
    try:
        # Cập nhật trạng thái đang chạy pipeline AI
        process_embed = create_process_embed(
            filename=filename,
            file_size=len(file_bytes),
            stage_desc="Demuxing Audio & Generating Vietsub..."
        )
        await interaction.edit_original_response(embed=process_embed)

        # Thực thi pipeline AI
        metrics = await bot_pipeline.process_file_to_srt(
            file_bytes=file_bytes,
            filename=filename
        )
        temp_dir_path = metrics.temp_dir
        execution_time = time.perf_counter() - start_time

        # Thành công: Khởi tạo Success Embed
        success_embed = discord.Embed(
            title="<:50919aseprite:1548611674418847814> VIETSUB COMPLETED",
            description="Tiến trình bóc tách phụ đề và chuyển ngữ ngữ cảnh hoàn tất. File `.srt` đã được đóng gói sẵn sàng xuất bản.",
            color=0x00FFA3,
            timestamp=datetime.now(timezone.utc)
        )

        success_embed.add_field(
            name="<:50919aseprite:1548611674418847814> Source Media",
            value=f"```fix\nName: {filename}\nSize: {format_bytes(len(file_bytes))}\nLength: {format_duration(metrics.audio_duration)}\n```",
            inline=False
        )

        inference_ratio = metrics.audio_duration / max(0.1, execution_time)
        telemetry_info = (
            f"• **Segments Created:** `{metrics.segment_count}` khối phụ đề\n"
            f"• **Source Language:** `{metrics.detected_language}`\n"
            f"• **Processing Latency:** `{execution_time:.2f}s`\n"
            f"• **Throughput Speed:** `{inference_ratio:.1f}x realtime`"
        )
        success_embed.add_field(name="Telemetry & Benchmark", value=telemetry_info, inline=False)

        arch_info = (
            "`STT Engine:` **OpenAI Whisper Large-v3**\n"
            "`LLM Engine:` **Google Gemini 3.5 Flash-Lite**\n"
            "`Node Cluster:` **Ryzen 9 7900**"
        )
        success_embed.add_field(name="Computational Stack", value=arch_info, inline=False)

        success_embed.set_footer(
            text=f"Vietsub Studio Enterprise • Session ID: {interaction.id}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
        )

        # Chỉnh sửa chính tin nhắn đang processing sang success và đính kèm file .srt
        discord_file = discord.File(str(metrics.srt_path), filename=metrics.srt_path.name)
        await interaction.edit_original_response(embed=success_embed, attachments=[discord_file])

    except Exception as e:
        logger.error(f"Lỗi thực thi pipeline /vsub: {str(e)}", exc_info=True)
        elapsed = time.perf_counter() - start_time

        fail_embed = discord.Embed(
            title="<:685108warn:1548610613528494121> PIPELINE EXECUTION FAILED",
            description="Đã xảy ra sự cố trong quá trình xử lý pipeline tự động.",
            color=0xFF3366,
            timestamp=datetime.now(timezone.utc)
        )
        fail_embed.add_field(
            name="Error Diagnostics",
            value=f"```py\n{type(e).__name__}: {str(e)[:400]}\n```",
            inline=False
        )
        fail_embed.add_field(
            name="Execution Metrics",
            value=f"• **Elapsed Before Crash:** `{elapsed:.2f}s`\n• **File Name:** `{filename}`",
            inline=False
        )
        fail_embed.set_footer(text="Hệ thống đã tự động ghi nhận crash log.")
        await interaction.edit_original_response(embed=fail_embed, attachments=[])

    finally:
        if temp_dir_path and os.path.exists(temp_dir_path):
            shutil.rmtree(temp_dir_path, ignore_errors=True)


class MediaURLModal(discord.ui.Modal, title="Vietsub Studio"):
    media_url = discord.ui.TextInput(
        label="Media URL",
        placeholder="https://.../video.mp4",
        style=discord.TextStyle.short,
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.media_url.value.strip()

        parsed_url = urllib.parse.urlparse(url)
        path = parsed_url.path
        filename = os.path.basename(path) or "remote_media.mp4"
        file_ext = os.path.splitext(filename)[1].lower()

        if not file_ext or file_ext not in ALLOWED_EXTENSIONS:
            filename = f"{filename}.mp4"
            file_ext = ".mp4"

        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()

        # Hiển thị embed Ingestion ngay lập tức
        downloading_embed = discord.Embed(
            title="<a:chiikawascuba:1548601830140022825> INGESTING REMOTE STREAM",
            description="Đang kết nối đến máy chủ nguồn để truyền tải payload dữ liệu...",
            color=0xF59E0B,
            timestamp=datetime.now(timezone.utc)
        )
        downloading_embed.add_field(
            name="Stream URL",
            value=f"```fix\n{url[:120]}...\n```" if len(url) > 120 else f"```fix\n{url}\n```",
            inline=False
        )
        await interaction.edit_original_response(embed=downloading_embed)

        try:
            timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        error_embed = discord.Embed(
                            title="<a:chiikawascuba:1548601830140022825> Download Failed",
                            description=f"Không thể tải media từ URL chỉ định (HTTP Status: `{response.status}`).",
                            color=0xFF3366,
                            timestamp=datetime.now(timezone.utc)
                        )
                        await interaction.edit_original_response(embed=error_embed)
                        return

                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                        size_embed = discord.Embed(
                            title="<a:chiikawascuba:1548601830140022825> Payload Entity Too Large",
                            description=f"Dung lượng tệp ({format_bytes(int(content_length))}) vượt quá ngưỡng tối đa cho phép ({format_bytes(MAX_FILE_SIZE_BYTES)}).",
                            color=0xFF3366,
                            timestamp=datetime.now(timezone.utc)
                        )
                        await interaction.edit_original_response(embed=size_embed)
                        return

                    chunks = []
                    total_downloaded = 0
                    while True:
                        chunk = await response.content.read(64 * 1024)
                        if not chunk:
                            break
                        total_downloaded += len(chunk)
                        if total_downloaded > MAX_FILE_SIZE_BYTES:
                            size_embed = discord.Embed(
                                title="<a:chiikawascuba:1548601830140022825> Payload Entity Too Large",
                                description=f"Dung lượng stream vượt quá ngưỡng tối đa ({format_bytes(MAX_FILE_SIZE_BYTES)}).",
                                color=0xFF3366,
                                timestamp=datetime.now(timezone.utc)
                            )
                            await interaction.edit_original_response(embed=size_embed)
                            return
                        chunks.append(chunk)

                    file_bytes = b"".join(chunks)

        except Exception as err:
            logger.error(f"Lỗi tải URL: {str(err)}", exc_info=True)
            error_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> URL Connection Error",
                description=f"Không thể kết nối tải tệp nguồn:\n`{str(err)[:300]}`",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc)
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        await run_pipeline(interaction, file_bytes, filename, start_time)


class VsubCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="vsub",
        description="Auto Sub & Translation"
    )
    @app_commands.describe(
        file="Tệp Media (Video/Audio). Để trống tùy chọn này để mở Modal nhập URL"
    )
    async def vsub(self, interaction: discord.Interaction, file: Optional[discord.Attachment] = None):
        # 1. Nếu không đính kèm file -> Mở Modal URL
        if file is None:
            await interaction.response.send_modal(MediaURLModal())
            return

        # 2. Upload file trực tiếp qua Discord
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in ALLOWED_EXTENSIONS:
            error_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> Invalid Media Format",
                description=f"Hệ thống không chấp nhận định dạng `{file_ext}`.",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc)
            )
            error_embed.add_field(
                name="Hỗ trợ chuẩn",
                value="`mp4`, `mov`, `mkv`, `webm`, `mp3`, `wav`, `m4a`",
                inline=False
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return

        if file.size > MAX_FILE_SIZE_BYTES:
            size_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> Payload Entity Too Large",
                description=f"Dung lượng tệp ({format_bytes(file.size)}) vượt quá ngưỡng tối đa cho phép ({format_bytes(MAX_FILE_SIZE_BYTES)}).",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc)
            )
            await interaction.response.send_message(embed=size_embed, ephemeral=True)
            return

        # Defer rồi ngay lập tức edit thành Process Embed
        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()

        initial_embed = create_process_embed(
            filename=file.filename,
            file_size=file.size,
            stage_desc="Reading payload bytes..."
        )
        await interaction.edit_original_response(embed=initial_embed)

        file_bytes = await file.read()
        await run_pipeline(interaction, file_bytes, file.filename, start_time)


async def setup(bot: commands.Bot):
    await bot.add_cog(VsubCommand(bot))