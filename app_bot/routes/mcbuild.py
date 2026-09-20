import asyncio
import logging
import time
from typing import List, Optional

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from app.api.v1.file_up import MCAutoBuildRequest, mc_auto_build

logger = logging.getLogger("Command_MCBuild")

# Danh sách 62 mods tối ưu mặc định cho Minecraft Fabric
DEFAULT_MODS = {
    "Accurate Block Placement": "kzwxhsjp",
    "AppleSkin": "EsAfCjCV",
    "Architectury API": "lhGA9TYQ",
    "BadOptimizations": "g96Z4WVZ",
    "CICADA": "IwCkru1D",
    "Cloth Config API": "9s6osm5g",
    "Collective": "e0M1UDsY",
    "Continuity": "1IjD5062",
    "CreativeCore": "OsZiaDHq",
    "Dynamic FPS": "LQ3K71Q1",
    "Easy Shulker Boxes": "gA5euN8S",
    "Entity Culling": "NNAgCjsB",
    "Entity Texture Features": "BVzZfTc1",
    "Entity Model Features": "4I1XuqiY",
    "Fabric API": "P7dR8mSH",
    "Fabric Language Kotlin": "Ha28R6CL",
    "Fabrishot": "3qsfQtE9",
    "Fast IP Ping": "9mtu0sUO",
    "Fast Trading": "Ht0RRAt0",
    "FerriteCore": "uXXizFIs",
    "Forge Config API Port": "ohNO6lps",
    "Freecam": "XeEZ3fK2",
    "Freelook": "g4pR0Fmy",
    "Gamma Utils": "wdLuzzEP",
    "ImmediatelyFast": "5ZwdcRci",
    "Inventory Profiles Next": "O7RBXm3n",
    "Iris Shaders": "YL57xq9U",
    "Jade": "nvQzSEkH",
    "libIPN": "onSQdWhM",
    "Lithium": "gvQqBUqZ",
    "MaLiLib": "GcWjdA9I",
    "MidnightLib": "codAaoxh",
    "Mod Menu": "mOgUt4GM",
    "More Mouse Tweaks": "S8drsznD",
    "Mouse Tweaks": "aC3cM3Vq",
    "MRU": "SNVQ2c0g",
    "No Chat Reports": "qQyHxfxd",
    "NoisiumForked": "hasdd01q",
    "Not Enough Animations": "MPCX6s5C",
    "owo lib": "ccKDOlHs",
    "Presence Footsteps": "rcTfTZr3",
    "Puzzles Lib": "QAGBst4M",
    "Puzzle": "3IuO68q1",
    "Reese's Sodium Options": "Bh37bMuy",
    "Show Me Your Skin!": "bD7YqcA3",
    "3D Skin Layers": "zV5r3pPn",
    "Smooth Scroll": "CllP7wW0",
    "Smooth Chat": "DnNYdJsx",
    "Sodium": "AANobbMI",
    "Sodium Extra": "PtjYWJkn",
    "Sound Physics Remastered": "qyVF9oeo",
    "Sounds": "ZouiUX7t",
    "Trade Cycling": "qpPoAL6m",
    "Transcending Trident": "7GxZi46W",
    "ukulib": "Y8uFrUil",
    "uku's Armor HUD": "wF189hn9",
    "Visible Traders": "AhllI99f",
    "Visuality": "rI0hvYcd",
    "Simple Voice Chat": "9eGKb6K1",
    "YetAnotherConfigLib": "1eAoo2KR",
    "Zoomify": "w7ThoJFB",
    "Fabric Tailor": "g8w1NapE",
}

# Danh sách phiên bản phổ biến để gợi ý khi người dùng chưa gõ hoặc gõ tìm kiếm
POPULAR_VERSIONS = [
    "1.21.11",
    "1.21.10",
    "1.21.9",
    "1.21.8",
    "1.21.7",
    "1.21.6",
    "1.21.5",
    "1.21.4",
    "1.21.3",
    "1.21.2",
    "1.21.1",
    "1.21",
    "1.20.6",
    "1.20.4",
    "1.20.2",
    "1.20.1",
    "1.20",
    "1.19.4",
    "1.19.2",
    "1.18.2",
    "1.16.5",
    "26.1.2",
    "26.1.1",
]

_CACHED_VERSIONS = list(POPULAR_VERSIONS)
_LAST_VERSION_FETCH = 0.0


async def get_available_versions() -> List[str]:
    """Lấy danh sách các phiên bản Minecraft từ cache hoặc Modrinth API."""
    global _CACHED_VERSIONS, _LAST_VERSION_FETCH
    now = time.time()
    if now - _LAST_VERSION_FETCH > 3600 or len(_CACHED_VERSIONS) <= len(POPULAR_VERSIONS):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.modrinth.com/v2/tag/game_version")
                if res.status_code == 200:
                    data = res.json()
                    release_versions = [
                        item["version"]
                        for item in data
                        if item.get("version_type") == "release"
                    ]
                    # Ghép các bản phổ biến lên đầu, sau đó tới các bản mới nhất
                    seen = set()
                    merged = []
                    for v in POPULAR_VERSIONS:
                        if v not in seen:
                            seen.add(v)
                            merged.append(v)
                    for v in release_versions:
                        if v not in seen:
                            seen.add(v)
                            merged.append(v)
                    _CACHED_VERSIONS = merged
                    _LAST_VERSION_FETCH = now
        except Exception as e:
            logger.warning(f"Không thể cập nhật danh sách version từ Modrinth: {e}")

    return _CACHED_VERSIONS


class MCBuildCog(commands.Cog, name="Minecraft"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="mcbuild",
        description="Tự động tải & đóng gói Modpack Minecraft tối ưu cho phiên bản mong muốn"
    )
    @app_commands.describe(
        version="Phiên bản Minecraft (chọn từ danh sách gợi ý hoặc tự nhập phiên bản của bạn)"
    )
    async def mcbuild(self, interaction: discord.Interaction, version: str):
        clean_version = version.strip()
        if not clean_version:
            await interaction.response.send_message(
                "Vui lòng nhập hoặc chọn phiên bản Minecraft hợp lệ!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        start_time = time.perf_counter()

        # Embed tiến trình
        building_embed = discord.Embed(
            title="MINECRAFT MODPACK BUILDER",
            description=f"Đang đồng bộ dữ liệu Modrinth và đóng gói bộ 62 mods tối ưu cho Minecraft **{clean_version}** (Fabric)...",
            color=0xF59E0B,
        )
        building_embed.add_field(
            name="Cấu Hình Bản Build",
            value=f"```fix\nVersion: {clean_version}\nLoader: Fabric\nTotal Mods: {len(DEFAULT_MODS)}\nOptimization Stack: Sodium + Lithium + Iris + FerriteCore\n```",
            inline=False,
        )
        building_embed.set_footer(text="Quá trình xử lý song song thường mất khoảng 3 - 6 giây...")
        await interaction.edit_original_response(embed=building_embed)

        try:
            req = MCAutoBuildRequest(
                version=clean_version,
                loader="fabric",
                mods=DEFAULT_MODS,
            )
            res = await mc_auto_build(req)

            # Nếu kết quả trả về là JSONResponse lỗi (vd 404, 400)
            if not isinstance(res, dict) or not res.get("success"):
                error_msg = "Không tìm thấy mod nào tương thích với phiên bản này."
                if isinstance(res, dict) and res.get("error"):
                    error_msg = res.get("error")
                fail_embed = discord.Embed(
                    title="BUILD MODPACK THẤT BẠI",
                    description=f"Không thể tạo bộ modpack cho Minecraft `{clean_version}`.\n**Lý do:** {error_msg}",
                    color=0xEF4444,
                )
                await interaction.edit_original_response(embed=fail_embed)
                return

            elapsed = time.perf_counter() - start_time
            file_id = res.get("fileId")
            zip_name = res.get("zipName")
            download_url = res.get("downloadUrl")
            direct_url = res.get("directUrl")
            total_packed = res.get("totalModsPacked", 0)
            total_requested = res.get("totalModsRequested", len(DEFAULT_MODS))
            missing_mods = res.get("missingMods", [])

            success_embed = discord.Embed(
                title="MINECRAFT MODPACK READY",
                description=f"Bộ modpack tối ưu cho Minecraft **{clean_version}** (Fabric) đã được đóng gói thành công!",
                color=0x10B981,
            )

            success_embed.add_field(
                name="Thông Tin Bản Build",
                value=(
                    f"```fix\n"
                    f"File Name: {zip_name}\n"
                    f"Game Version: {clean_version}\n"
                    f"Mod Loader: Fabric\n"
                    f"Mods Packed: {total_packed}/{total_requested} mods\n"
                    f"Build Time: {elapsed:.2f}s\n"
                    f"```"
                ),
                inline=False,
            )

            # Điểm nhanh một số mod cốt lõi
            core_highlights = (
                "• **Hiệu năng & Tối ưu:** Sodium, Lithium, FerriteCore, ImmediatelyFast, BadOptimizations\n"
                "• **Đồ họa & Hiệu ứng:** Iris Shaders, 3D Skin Layers, Continuity, Visuality\n"
                "• **Tiện ích & QoL:** AppleSkin, Jade, Mod Menu, Inventory Profiles Next, Freecam, Zoomify"
            )
            success_embed.add_field(name="Các Mod Cốt Lõi Đã Bao Gồm", value=core_highlights, inline=False)

            if missing_mods:
                missing_names = ", ".join(m["name"] for m in missing_mods[:5])
                if len(missing_mods) > 5:
                    missing_names += f" (+{len(missing_mods) - 5} mod khác)"
                success_embed.add_field(
                    name="Lưu ý các mod chưa có bản tương thích",
                    value=f"`{missing_names}`",
                    inline=False,
                )

            success_embed.set_footer(
                text=f"Elyriax Minecraft Studio • File ID: {file_id}",
                icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            )

            # Tạo nút bấm Link tải xuống
            view = discord.ui.View()
            if download_url and len(download_url) <= 512:
                view.add_item(
                    discord.ui.Button(
                        label="Tải Modpack (.ZIP)",
                        url=download_url,
                        style=discord.ButtonStyle.link,
                    )
                )
            if direct_url and len(direct_url) <= 512:
                view.add_item(
                    discord.ui.Button(
                        label="Tải Trực Tiếp (Direct)",
                        url=direct_url,
                        style=discord.ButtonStyle.link,
                    )
                )

            await interaction.edit_original_response(embed=success_embed, view=view)

        except Exception as e:
            logger.error(f"Lỗi khi thực thi lệnh /mcbuild: {e}", exc_info=True)
            fail_embed = discord.Embed(
                title="LỖI HỆ THỐNG",
                description=f"Đã xảy ra sự cố ngoài ý muốn khi đóng gói modpack:\n`{str(e)[:300]}`",
                color=0xEF4444,
            )
            await interaction.edit_original_response(embed=fail_embed)

    @mcbuild.autocomplete("version")
    async def mcbuild_version_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Gợi ý danh sách phiên bản Minecraft theo ký tự người dùng gõ."""
        versions = await get_available_versions()
        current_lower = current.strip().lower()

        if not current_lower:
            # Khi chưa gõ gì: hiển thị top các bản phổ biến nhất
            return [
                app_commands.Choice(name=f"Minecraft {v} (Fabric)", value=v)
                for v in versions[:25]
            ]

        # Khi người dùng đang gõ: lọc những bản khớp với chuỗi tìm kiếm
        matches = [v for v in versions if current_lower in v.lower()]

        # Nếu phiên bản người dùng gõ hoàn toàn mới (chưa có trong danh sách), thêm lựa chọn tự nhập lên đầu
        choices = []
        if current.strip() and not any(v.lower() == current_lower for v in matches):
            choices.append(
                app_commands.Choice(
                    name=f"Tự nhập: {current.strip()}",
                    value=current.strip(),
                )
            )

        for v in matches:
            if len(choices) >= 25:
                break
            choices.append(app_commands.Choice(name=f"Minecraft {v}", value=v))

        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(MCBuildCog(bot))

