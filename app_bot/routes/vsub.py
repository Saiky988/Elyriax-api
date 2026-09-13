import os
import shutil
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from app_bot.services.pipeline import bot_pipeline

logger = logging.getLogger("Command_Vsub")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 50 MB Payload Limit


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


class VsubCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="vsub",
        description="Auto Sub & Translation"
    )
    @app_commands.describe(
        file="Tệp Media (Video/Audio) cần bóc tách phụ đề và chuyển ngữ Vietsub"
    )
    async def vsub(self, interaction: discord.Interaction, file: discord.Attachment):
        file_ext = os.path.splitext(file.filename)[1].lower()

        # 1. Validation định dạng tệp đầu vào
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

        # 2. Validation dung lượng payload
        if file.size > MAX_FILE_SIZE_BYTES:
            size_embed = discord.Embed(
                title="<a:chiikawascuba:1548601830140022825> Payload Entity Too Large",
                description=f"Dung lượng tệp ({format_bytes(file.size)}) vượt quá ngưỡng tối đa cho phép ({format_bytes(MAX_FILE_SIZE_BYTES)}).",
                color=0xFF3366,
                timestamp=datetime.now(timezone.utc)
            )
            await interaction.response.send_message(embed=size_embed, ephemeral=True)
            return

        # Defer tương tác chống timeout Discord gateway
        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()
        temp_dir_path = None

        try:
            # Tải payload về bộ nhớ đệm
            file_bytes = await file.read()

            # Thực thi pipeline xử lý phân tầng
            metrics = await bot_pipeline.process_file_to_srt(
                file_bytes=file_bytes,
                filename=file.filename
            )
            temp_dir_path = metrics.temp_dir
            execution_time = time.perf_counter() - start_time

            # Xây dựng Industrial Success Embed (Telemetry & Benchmark thuần túy)
            success_embed = discord.Embed(
                title="<:50919aseprite:1548611674418847814> VIETSUB COMPLETED",
                description="Tiến trình bóc tách phụ đề và chuyển ngữ ngữ cảnh hoàn tất. File `.srt` đã được đóng gói sẵn sàng xuất bản.",
                color=0x00FFA3,
                timestamp=datetime.now(timezone.utc)
            )

            # Metadata tệp nguồn
            success_embed.add_field(
                name="<:50919aseprite:1548611674418847814> Source Media",
                value=f"```fix\nName: {file.filename}\nSize: {format_bytes(file.size)}\nLength: {format_duration(metrics.audio_duration)}\n```",
                inline=False
            )

            # Chỉ số viễn trắc AI
            inference_ratio = metrics.audio_duration / max(0.1, execution_time)
            telemetry_info = (
                f"• **Segments Created:** `{metrics.segment_count}` khối phụ đề\n"
                f"• **Source Language:** `{metrics.detected_language}`\n"
                f"• **Processing Latency:** `{execution_time:.2f}s`\n"
                f"• **Throughput Speed:** `{inference_ratio:.1f}x realtime`"
            )
            success_embed.add_field(name="Telemetry & Benchmark", value=telemetry_info, inline=False)

            # Hạ tầng & Mô hình tính toán
            arch_info = (
                "`STT Engine:` **Whisper Large-v3**\n"
                "`LLM Engine:` **Google Gemini 3.1 Flash-Lite**\n"
                "`Node Cluster:` **Ryzen 9 7900**"
            )
            success_embed.add_field(name="Computational Stack", value=arch_info, inline=False)

            success_embed.set_footer(
                text=f"Vietsub Studio Enterprise • Session ID: {interaction.id}",
                icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
            )

            discord_file = discord.File(str(metrics.srt_path), filename=metrics.srt_path.name)
            await interaction.followup.send(
                embed=success_embed,
                file=discord_file
            )

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
                value=f"• **Elapsed Before Crash:** `{elapsed:.2f}s`\n• **File Name:** `{file.filename}`",
                inline=False
            )
            fail_embed.set_footer(text="Hệ thống đã tự động ghi nhận crash log.")

            await interaction.followup.send(embed=fail_embed)

        finally:
            if temp_dir_path and os.path.exists(temp_dir_path):
                shutil.rmtree(temp_dir_path, ignore_errors=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VsubCommand(bot))
