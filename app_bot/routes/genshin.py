import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from app.core.database import execute, fetch_all, fetch_one, get_connection
from app.services.genshin.account_service import (
    add_account,
    get_accounts,
    get_ready_genshin_payload,
    update_account,
)
from app.services.genshin.banner import get_banners
from app.services.genshin.checkin import check_in_daily
from app.services.genshin.checkin_list import get_check_in_list
from app.services.genshin.codes import get_all_codes
from app.services.genshin.daily_note import get_daily_note
from app.services.genshin.redeem import redeem_code
from app.services.genshin.stats import get_role_and_stats

logger = logging.getLogger("Command_Genshin")

COLOR_GOLD = 0xF59E0B
COLOR_CYAN = 0x06B6D4
COLOR_PURPLE = 0x8B5CF6
COLOR_GREEN = 0x10B981
COLOR_RED = 0xEF4444
COLOR_BLUE = 0x3B82F6
COLOR_PINK = 0xEC4899

GENSHIN_LOGO_URL = "https://assets.stickpng.com/images/6016e379650b280004dc5891.png"
PRIMOGEM_ICON_URL = "https://static.wikia.nocookie.net/gensin-impact/images/d/d4/Item_Primogem.png"
RESIN_ICON_URL = "https://static.wikia.nocookie.net/gensin-impact/images/3/35/Item_Fragile_Resin.png"


def make_progress_bar(current: int, max_val: int, length: int = 10) -> str:
    if max_val <= 0:
        return "░" * length
    ratio = min(max(current / max_val, 0.0), 1.0)
    filled = int(round(ratio * length))
    empty = length - filled
    percent = int(ratio * 100)
    return f"`[{'█' * filled}{'░' * empty}]` **{current}/{max_val}** ({percent}%)"


async def get_or_create_discord_user(discord_user: discord.User | discord.Member) -> int:
    oauth = await fetch_one(
        "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
        (str(discord_user.id),),
    )
    if oauth:
        return oauth["user_id"]

    username = f"discord_{discord_user.name}"
    display_name = discord_user.display_name or discord_user.name
    avatar_url = discord_user.display_avatar.url if discord_user.display_avatar else None

    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO users (username, display_name, avatar, role, status) VALUES (%s, %s, %s, 'user', 'active')",
                    (username, display_name, avatar_url),
                )
                user_id = cur.lastrowid

                await cur.execute(
                    "INSERT INTO user_oauth_accounts (user_id, provider, provider_user_id, email, username) VALUES (%s, 'discord', %s, NULL, %s)",
                    (user_id, str(discord_user.id), discord_user.name),
                )
                await conn.commit()
                return user_id
            except Exception:
                await conn.rollback()
                raise


async def get_user_genshin_payload(discord_user: discord.User | discord.Member, account_id: Optional[int] = None) -> Dict[str, Any]:
    oauth = await fetch_one(
        "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
        (str(discord_user.id),),
    )
    if not oauth:
        raise ValueError(
            "❌ **Bạn chưa liên kết tài khoản Genshin Impact!**\n"
            "👉 Hãy sử dụng lệnh `/genshin link` để liên kết tài khoản HoYoLAB an toàn ngay trong Discord."
        )
    user_id = oauth["user_id"]

    if account_id:
        return await get_ready_genshin_payload(user_id, account_id)

    row = await fetch_one(
        "SELECT id FROM genshin_accounts WHERE user_id = %s AND is_default = TRUE AND status = 'active'",
        (user_id,),
    )
    if not row:
        row = await fetch_one(
            "SELECT id FROM genshin_accounts WHERE user_id = %s AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
    if not row:
        raise ValueError(
            "❌ **Bạn chưa có tài khoản Genshin nào được liên kết!**\n"
            "👉 Hãy sử dụng lệnh `/genshin link` để thêm tài khoản Genshin của bạn."
        )
    return await get_ready_genshin_payload(user_id, row["id"])


class CodesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Trang Đổi Code HoYoverse",
                url="https://genshin.hoyoverse.com/en/gift",
                style=discord.ButtonStyle.link,
                emoji="🎁",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Fandom Wiki",
                url="https://genshin-impact.fandom.com/wiki/Promotional_Code",
                style=discord.ButtonStyle.link,
                emoji="📖",
            )
        )


class GenshinLinkModal(discord.ui.Modal, title="Liên Kết HoYoLAB Genshin Impact"):
    cookie = discord.ui.TextInput(
        label="Cookie HoYoLAB (ltuid_v2 & ltoken_v2)",
        style=discord.TextStyle.paragraph,
        placeholder="Dán toàn bộ chuỗi cookie lấy từ trang hoyolab.com...",
        required=True,
        min_length=20,
        max_length=2000,
    )
    uid = discord.ui.TextInput(
        label="UID Trong Game Genshin Impact",
        placeholder="VD: 812345678",
        required=True,
        min_length=9,
        max_length=10,
    )
    server = discord.ui.TextInput(
        label="Máy Chủ (Server)",
        placeholder="os_asia (Asia), os_usa (NA), os_euro (EU), os_cht (TW/HK)",
        default="os_asia",
        required=True,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = await get_or_create_discord_user(interaction.user)
            server_val = self.server.value.strip().lower()
            server_map = {
                "asia": "os_asia",
                "na": "os_usa",
                "america": "os_usa",
                "eu": "os_euro",
                "europe": "os_euro",
                "tw": "os_cht",
                "hk": "os_cht",
            }
            norm_server = server_map.get(server_val, server_val)

            res = await add_account(
                user_id,
                {
                    "cookie": self.cookie.value.strip(),
                    "uid": self.uid.value.strip(),
                    "server": norm_server,
                },
            )

            embed = discord.Embed(
                title="✅ LIÊN KẾT TÀI KHOẢN GENSHIN THÀNH CÔNG",
                description="Tài khoản HoYoLAB của bạn đã được mã hóa an toàn bằng thuật toán **AES-256-CBC** vào hệ thống Elyriax.",
                color=COLOR_GREEN,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=GENSHIN_LOGO_URL)
            embed.add_field(name="Tên Nhân Vật (Nickname)", value=f"**{res.get('nickname')}**", inline=True)
            embed.add_field(name="UID Game", value=f"`{res.get('uid')}`", inline=True)
            embed.add_field(name="Máy Chủ", value=f"`{res.get('server').upper()}`", inline=True)
            embed.add_field(
                name="Trạng Thái Tự Động",
                value="• 🌟 **Tự động điểm danh hàng ngày:** Bật\n• 🎁 **Tự động nhận Giftcode:** Sẵn sàng\n• ⚡ **Theo dõi Nhựa thời gian thực:** Sẵn sàng",
                inline=False,
            )
            embed.set_footer(text="Elyriax Genshin System • Bảo mật cấp ngân hàng", icon_url=PRIMOGEM_ICON_URL)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Genshin link modal error: {e}")
            await interaction.followup.send(f"❌ **Lỗi liên kết:** {str(e)}", ephemeral=True)


class GenshinCog(commands.Cog, name="Genshin Impact"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    genshin_group = app_commands.Group(name="genshin", description="Hệ thống tự động hóa và tiện ích Genshin Impact")

    # ----------------------------------------------------
    # 1. /genshin codes
    # ----------------------------------------------------
    @genshin_group.command(name="codes", description="Tra cứu toàn bộ giftcode Genshin Impact mới nhất kèm phần thưởng")
    async def genshin_codes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cards = await get_all_codes()
            if not cards:
                await interaction.followup.send("⚠️ Hiện không có giftcode nào khả dụng hoặc không thể nạp từ wiki.")
                return

            embed = discord.Embed(
                title="✨ DANH SÁCH GIFTCODE GENSHIN IMPACT ĐANG HOẠT ĐỘNG",
                description=(
                    f"Tìm thấy **{len(cards)} mã quà tặng** khả dụng được cập nhật thời gian thực từ Fandom Wiki.\n"
                    "👉 Dùng `/genshin redeem <mã>` để đổi quà tự động trực tiếp cho tài khoản!"
                ),
                color=COLOR_GOLD,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            for idx, c in enumerate(cards[:10], start=1):
                code_str = " / ".join([f"`{code}`" for code in c.get("codes", [])])
                rewards_str = " • ".join(c.get("rewards", [])) or "Quà tặng trong game"
                server_str = c.get("server", "Toàn cầu")
                validity_str = c.get("validity") or "Không xác định"

                field_value = (
                    f"**Mã Code:** {code_str}\n"
                    f"**Phần thưởng:** {rewards_str}\n"
                    f"**Khu vực:** `{server_str}` | **Hạn:** *{validity_str}*"
                )
                embed.add_field(name=f"#{idx} Quà Tặng", value=field_value, inline=False)

            embed.set_footer(text="Elyriax Hub • Dữ liệu Fandom Wiki", icon_url=GENSHIN_LOGO_URL)
            await interaction.followup.send(embed=embed, view=CodesView())
        except Exception as e:
            logger.error(f"Error /genshin codes: {e}")
            await interaction.followup.send(f"❌ Lỗi khi lấy danh sách mã code: {e}")

    # ----------------------------------------------------
    # 2. /genshin banner
    # ----------------------------------------------------
    @genshin_group.command(name="banners", description="Xem thông tin banner nhân vật & vũ khí Genshin Impact hiện tại")
    async def genshin_banners(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            banners = await get_banners()
            if not banners:
                await interaction.followup.send("⚠️ Chưa có dữ liệu banner khả dụng.")
                return

            active_banner = next((b for b in banners if b.get("going_on")), banners[0])

            version = active_banner.get("version", "N/A")
            phase = active_banner.get("phase", "Phase 1")
            name = active_banner.get("name", "Event Wish")
            status = "🟢 ĐANG DIỄN RA" if active_banner.get("going_on") else "🟡 SẮP DIỄN RA"

            five_stars_new = active_banner.get("5_star_featured", {}).get("new", [])
            five_stars_rerun = active_banner.get("5_star_featured", {}).get("rerun", [])
            five_stars = five_stars_new + five_stars_rerun
            four_stars = active_banner.get("4_star_featured", [])
            weapons = active_banner.get("weapon_banner", [])

            start_date = active_banner.get("start_date", "").replace("T", " ").replace("Z", "")
            end_date = active_banner.get("end_date", "").replace("T", " ").replace("Z", "")

            embed = discord.Embed(
                title=f"🌠 CẦU NGUYỆN GENSHIN IMPACT — PHIÊN BẢN {version} ({phase})",
                description=f"**Chủ đề:** *{name}* • **Trạng thái:** `{status}`",
                color=COLOR_PURPLE,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url="https://static.wikia.nocookie.net/gensin-impact/images/a/ab/Item_Intertwined_Fate.png")

            embed.add_field(
                name="⭐ Nhân Vật 5 Sao Rate-Up",
                value="\n".join([f"• ⭐⭐⭐⭐⭐ **{c}**" for c in five_stars]) or "• Chưa công bố",
                inline=False,
            )
            embed.add_field(
                name="⭐ Nhân Vật 4 Sao Đi Kèm",
                value=" • ".join([f"**{c}**" for c in four_stars]) or "Chưa công bố",
                inline=False,
            )
            embed.add_field(
                name="⚔️ Thân Hình Đúc Kết (Vũ Khí 5 Sao)",
                value="\n".join([f"• 🗡️ **{w.replace('_', ' ')}**" for w in weapons]) or "Chưa công bố",
                inline=False,
            )
            embed.add_field(
                name="⏰ Thời Gian Diễn Ra",
                value=f"• **Bắt đầu:** `{start_date} UTC`\n• **Kết thúc:** `{end_date} UTC`",
                inline=False,
            )

            embed.set_footer(text="Elyriax Genshin Tracker • Dữ liệu chính thức & Dự đoán", icon_url=GENSHIN_LOGO_URL)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error /genshin banners: {e}")
            await interaction.followup.send(f"❌ Lỗi khi tải dữ liệu banner: {e}")

    # ----------------------------------------------------
    # 3. /genshin checkin
    # ----------------------------------------------------
    @genshin_group.command(name="checkin", description="Điểm danh HoYoLAB nhận quà hàng ngày ngay lập tức")
    async def genshin_checkin(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await check_in_daily(payload)

            claimed = res.get("claimed", False)
            title = "🎉 ĐIỂM DANH THÀNH CÔNG!" if claimed else "✨ HÔM NAY BẠN ĐÃ ĐIỂM DANH RỒI!"
            color = COLOR_GREEN if claimed else COLOR_CYAN

            today_reward = res.get("today_reward") or {}
            tomorrow_reward = res.get("tomorrow_reward") or {}

            embed = discord.Embed(
                title=f"📅 {title}",
                description=f"Điểm danh HoYoLAB cho Nhà Khai Phá: **{res.get('nickname')}** (UID: `{res.get('uid')}`)",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            if today_reward.get("icon"):
                embed.set_thumbnail(url=today_reward["icon"])
            else:
                embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            embed.add_field(name="Máy Chủ", value=f"`{res.get('server')}`", inline=True)
            embed.add_field(name="Cấp Thám Hiểm (AR)", value=f"`AR {res.get('adventure_rank', 'N/A')}`", inline=True)
            embed.add_field(
                name="Tiến Độ Điểm Danh",
                value=f"`{res.get('signed_days')}/{res.get('total_days_month')}` ngày",
                inline=True,
            )

            if today_reward:
                embed.add_field(
                    name="🎁 Phần Thưởng Hôm Nay",
                    value=f"**{today_reward.get('name')}** × `{today_reward.get('count')}`",
                    inline=False,
                )

            if tomorrow_reward:
                embed.add_field(
                    name="⏳ Phần Thưởng Ngày Mai",
                    value=f"**{tomorrow_reward.get('name')}** × `{tomorrow_reward.get('count')}`",
                    inline=False,
                )

            embed.set_footer(text="Elyriax Auto-Checkin • Điểm danh mượt mà mỗi ngày", icon_url=GENSHIN_LOGO_URL)
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin checkin: {e}")
            await interaction.followup.send(f"❌ Thất bại khi điểm danh: {e}")

    # ----------------------------------------------------
    # 4. /genshin daily_note
    # ----------------------------------------------------
    @genshin_group.command(name="daily_note", description="Kiểm tra Nhựa nguyên bản, Ủy thác, Boss tuần và Phái đi thám hiểm")
    async def genshin_daily_note(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await get_daily_note(payload)

            if not res.get("ok"):
                await interaction.followup.send(f"❌ Không thể tải Daily Note: {res.get('error')}")
                return

            data = res["data"]
            resin = data.get("resin", {})
            tasks = data.get("daily_tasks", {})
            expeditions = data.get("expeditions", {})
            home_coin = data.get("home_coin", {})
            transformer = data.get("transformer", {})

            cur_resin = resin.get("current", 0)
            max_resin = resin.get("max", 200)
            full_time = resin.get("estimated_full_time", "Đã đầy")

            embed = discord.Embed(
                title="⚡ GENSHIN IMPACT — REAL-TIME DAILY NOTE",
                description="Báo cáo tài nguyên và trạng thái thời gian thực tài khoản Genshin Impact:",
                color=COLOR_CYAN,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=RESIN_ICON_URL)

            # Resin progress
            resin_bar = make_progress_bar(cur_resin, max_resin, 12)
            embed.add_field(
                name="🌙 Nhựa Nguyên Bản (Original Resin)",
                value=f"{resin_bar}\n• **Thời gian hồi đầy:** `{full_time}`",
                inline=False,
            )

            # Daily Tasks
            task_fin = tasks.get("finished_num", 0)
            task_total = tasks.get("total_num", 4)
            extra_claimed = "✅ Đã nhận" if tasks.get("is_extra_reward_received") else "⏳ Chưa nhận"
            task_bar = make_progress_bar(task_fin, task_total, 8)
            embed.add_field(
                name="📜 Nhiệm Vụ Ủy Thác Hàng Ngày",
                value=f"{task_bar}\n• **Thưởng Katherine:** {extra_claimed}",
                inline=True,
            )

            # Boss discount
            remain_boss = resin.get("resin_discount", {}).get("remain_num", 0)
            limit_boss = resin.get("resin_discount", {}).get("limit_num", 3)
            embed.add_field(
                name="⚔️ Giảm Nửa Nhựa Boss Tuần",
                value=f"`{remain_boss}/{limit_boss}` lượt còn lại",
                inline=True,
            )

            # Home coin
            coin_cur = home_coin.get("current", 0)
            coin_max = home_coin.get("max", 2400)
            coin_full = home_coin.get("estimated_full_time", "Đã đầy")
            coin_bar = make_progress_bar(coin_cur, coin_max, 8)
            embed.add_field(
                name="🏡 Tiền Động Tiên (Serenitea Pot)",
                value=f"{coin_bar}\n• **Đầy lúc:** `{coin_full}`",
                inline=True,
            )

            # Expeditions
            exp_list = expeditions.get("list", [])
            exp_lines = []
            for idx, exp in enumerate(exp_list, 1):
                st = "✅ Xong" if exp.get("status") == "Finished" else f"⏳ {exp.get('estimated_finished_time')}"
                exp_lines.append(f"• **Slot {idx}:** {st}")

            embed.add_field(
                name=f"🧭 Phái Đi Thám Hiểm ({expeditions.get('current_num')}/{expeditions.get('max_num')})",
                value="\n".join(exp_lines) or "Không có nhân vật nào phái đi.",
                inline=True,
            )

            # Transformer
            trans_ready = "✅ Sẵn sàng sử dụng!" if transformer.get("ready") else "⏳ Đang hồi lại"
            embed.add_field(name="🔮 Máy Biến Đổi Chất Lượng", value=trans_ready, inline=True)

            embed.set_footer(text="Elyriax Daily Monitor • Đồng bộ trực tiếp từ HoYoLAB", icon_url=GENSHIN_LOGO_URL)
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin daily_note: {e}")
            await interaction.followup.send(f"❌ Lỗi khi tải Daily Note: {e}")

    # ----------------------------------------------------
    # 5. /genshin stats
    # ----------------------------------------------------
    @genshin_group.command(name="stats", description="Xem chiến tích tài khoản: AR, ngày chơi, thành tựu, rương và thần đồng")
    async def genshin_stats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await get_role_and_stats(payload)

            if not res.get("ok"):
                await interaction.followup.send(f"❌ Không thể tải chiến tích: {res.get('message')}")
                return

            role = res.get("role", {})
            stats = res.get("stats", {})
            chests = stats.get("chests", {})
            oculus = stats.get("oculus", {})

            embed = discord.Embed(
                title="🏆 CHIẾN TÍCH TÀI KHOẢN GENSHIN IMPACT",
                description=f"Nhà Khám Phá: **{role.get('nickname')}** • **Cấp Thám Hiểm (AR):** `{role.get('level')}`",
                color=COLOR_PINK,
                timestamp=datetime.now(timezone.utc),
            )
            if role.get("avatar_url"):
                embed.set_thumbnail(url=role["avatar_url"])
            else:
                embed.set_thumbnail(url=GENSHIN_LOGO_URL)

            embed.add_field(name="📅 Ngày Hoạt Động", value=f"`{stats.get('active_days', 0)}` ngày", inline=True)
            embed.add_field(name="🏅 Thành Tựu Đạt Được", value=f"`{stats.get('achievements', 0)}` cái", inline=True)
            embed.add_field(name="👥 Số Nhân Vật", value=f"`{stats.get('avatars_count', 0)}` nhân vật", inline=True)
            embed.add_field(name="🌀 La Hoàn Thâm Cảnh", value=f"`{stats.get('spiral_abyss', 'Chưa vào')}`", inline=True)
            embed.add_field(name="📍 Điểm Dịch Chuyển", value=f"`{stats.get('way_points', 0)}` điểm", inline=True)
            embed.add_field(name="🏛️ Bí Cảnh Đã Mở", value=f"`{stats.get('domains', 0)}` bí cảnh", inline=True)

            chests_text = (
                f"• Thường: `{chests.get('common', 0)}`\n"
                f"• Cao Cấp: `{chests.get('exquisite', 0)}`\n"
                f"• Hiếm: `{chests.get('precious', 0)}`\n"
                f"• Siêu Cấp: `{chests.get('luxurious', 0)}`"
            )
            embed.add_field(name="📦 Thống Kê Mở Rương", value=chests_text, inline=True)

            oculus_text = (
                f"• Phong: `{oculus.get('anemo', 0)}` • Nham: `{oculus.get('geo', 0)}`\n"
                f"• Lôi: `{oculus.get('electro', 0)}` • Thảo: `{oculus.get('dendro', 0)}`\n"
                f"• Thủy: `{oculus.get('hydro', 0)}` • Hỏa: `{oculus.get('pyro', 0)}`"
            )
            embed.add_field(name="✨ Thần Đồng Thu Thập", value=oculus_text, inline=True)

            embed.set_footer(text="Elyriax Battle Chronicle • Dữ liệu chính thức HoYoLAB", icon_url=PRIMOGEM_ICON_URL)
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin stats: {e}")
            await interaction.followup.send(f"❌ Lỗi khi tải chiến tích: {e}")

    # ----------------------------------------------------
    # 6. /genshin redeem <code>
    # ----------------------------------------------------
    @genshin_group.command(name="redeem", description="Đổi giftcode nhận quà trực tiếp cho tài khoản Genshin của bạn")
    @app_commands.describe(code="Mã giftcode cần đổi (VD: GENSHINGIFT)")
    async def genshin_redeem(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            payload["code"] = code.strip().upper()

            res = await redeem_code(payload)
            ok = res.get("ok", False)
            title = "🎁 NHẬP MÃ GIFTCODE THÀNH CÔNG!" if ok else "⚠️ NHẬP CODE KHÔNG THÀNH CÔNG"
            color = COLOR_GREEN if ok else COLOR_RED

            embed = discord.Embed(
                title=title,
                description=f"**Mã quà tặng:** `{code.strip().upper()}`\n**Thông báo hệ thống:** {res.get('message') or res.get('error')}",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            rewards = res.get("rewards", [])
            if rewards:
                embed.add_field(name="Phần Thưởng Nhận Được", value=" • ".join(rewards), inline=False)

            if res.get("uid"):
                embed.add_field(name="UID Nhận", value=f"`{res.get('uid')}`", inline=True)
                embed.add_field(name="Server", value=f"`{res.get('server')}`", inline=True)

            embed.set_footer(text="Elyriax Code Redemption Service", icon_url=GENSHIN_LOGO_URL)
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin redeem: {e}")
            await interaction.followup.send(f"❌ Thất bại khi đổi code: {e}")

    # ----------------------------------------------------
    # 7. /genshin link
    # ----------------------------------------------------
    @genshin_group.command(name="link", description="Liên kết tài khoản Genshin Impact bảo mật qua Modal Discord")
    async def genshin_link(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GenshinLinkModal())

    # ----------------------------------------------------
    # 8. /genshin accounts
    # ----------------------------------------------------
    @genshin_group.command(name="accounts", description="Xem danh sách các tài khoản Genshin đã liên kết")
    async def genshin_accounts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                await interaction.followup.send(
                    "❌ Bạn chưa liên kết tài khoản nào! Hãy dùng `/genshin link` để thêm tài khoản.",
                    ephemeral=True,
                )
                return

            accounts = await get_accounts(oauth["user_id"])
            if not accounts:
                await interaction.followup.send(
                    "⚠️ Bạn chưa có tài khoản Genshin nào! Hãy dùng `/genshin link` để liên kết.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="📋 DANH SÁCH TÀI KHOẢN GENSHIN ĐÃ LIÊN KẾT",
                description=f"Tìm thấy **{len(accounts)} tài khoản** thuộc người dùng **{interaction.user.display_name}**:",
                color=COLOR_BLUE,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=GENSHIN_LOGO_URL)

            for acc in accounts:
                is_def = "⭐ **[Mặc định]**" if acc.get("is_default") else ""
                checkin_status = "✅ Bật" if acc.get("auto_checkin") else "❌ Tắt"
                val = (
                    f"• **UID:** `{acc.get('uid')}`\n"
                    f"• **Máy chủ:** `{acc.get('server', '').upper()}`\n"
                    f"• **Auto Check-in:** {checkin_status}\n"
                    f"• **Account ID:** `{acc.get('id')}`"
                )
                embed.add_field(name=f"🎮 {acc.get('nickname', 'Nhà Khai Phá')} {is_def}", value=val, inline=False)

            embed.set_footer(text="Dùng /genshin switch <id> để đổi tài khoản mặc định")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error /genshin accounts: {e}")
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)

    # ----------------------------------------------------
    # 9. /genshin switch <account_id>
    # ----------------------------------------------------
    @genshin_group.command(name="switch", description="Đặt tài khoản Genshin làm tài khoản mặc định")
    @app_commands.describe(account_id="ID tài khoản trong lệnh /genshin accounts")
    async def genshin_switch(self, interaction: discord.Interaction, account_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                await interaction.followup.send("❌ Bạn chưa liên kết tài khoản nào.", ephemeral=True)
                return

            await update_account(oauth["user_id"], account_id, {"is_default": True})
            await interaction.followup.send(
                f"✅ Đã đặt tài khoản ID `{account_id}` làm tài khoản mặc định thành công!",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error /genshin switch: {e}")
            await interaction.followup.send(f"❌ Lỗi khi chuyển tài khoản: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GenshinCog(bot))
