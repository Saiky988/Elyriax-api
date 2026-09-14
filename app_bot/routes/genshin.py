import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one, get_connection
from app.services.auth_service import create_default_user_settings
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

COLOR_GOLD = 0xD97706
COLOR_CYAN = 0x0891B2
COLOR_PURPLE = 0x7C3AED
COLOR_GREEN = 0x059669
COLOR_RED = 0xDC2626
COLOR_BLUE = 0x2563EB
COLOR_PINK = 0xDB2777

GENSHIN_LOGO_URL = "https://assets.stickpng.com/images/6016e379650b280004dc5891.png"
PRIMOGEM_ICON_URL = "https://static.wikia.nocookie.net/gensin-impact/images/d/d4/Item_Primogem.png"
RESIN_ICON_URL = "https://static.wikia.nocookie.net/gensin-impact/images/3/35/Item_Fragile_Resin.png"


def make_progress_bar(current: int, max_val: int, length: int = 10) -> str:
    if max_val <= 0:
        return "-" * length
    ratio = min(max(current / max_val, 0.0), 1.0)
    filled = int(round(ratio * length))
    empty = length - filled
    percent = int(ratio * 100)
    return f"`[{'=' * filled}{'-' * empty}]` **{current}/{max_val}** ({percent}%)"


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
                    "INSERT INTO users (username, avatar, status) VALUES (%s, %s, 'active')",
                    (username, avatar_url),
                )
                user_id = cur.lastrowid

                await cur.execute(
                    """
                    INSERT INTO user_oauth_accounts 
                    (user_id, provider, provider_user_id, provider_name, provider_avatar) 
                    VALUES (%s, 'discord', %s, %s, %s)
                    """,
                    (user_id, str(discord_user.id), display_name, avatar_url),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    try:
        await create_default_user_settings(user_id)
    except Exception as e:
        logger.warning(f"Could not create default settings for user {user_id}: {e}")

    return user_id


async def get_user_genshin_payload(discord_user: discord.User | discord.Member, account_id: Optional[int] = None) -> Dict[str, Any]:
    oauth = await fetch_one(
        "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
        (str(discord_user.id),),
    )
    if not oauth:
        raise ValueError(
            "Ban chua lien ket tai khoan Genshin Impact. Su dung lenh /genshin link de them tai khoan."
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
            "Ban chua co tai khoan Genshin nao duoc them. Su dung lenh /genshin link de them tai khoan."
        )
    return await get_ready_genshin_payload(user_id, row["id"])


class CodesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Trang Doi Code HoYoverse",
                url="https://genshin.hoyoverse.com/en/gift",
                style=discord.ButtonStyle.link,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Fandom Wiki",
                url="https://genshin-impact.fandom.com/wiki/Promotional_Code",
                style=discord.ButtonStyle.link,
            )
        )


class GenshinLinkModal(discord.ui.Modal, title="Lien Ket HoYoLAB Genshin Impact"):
    cookie = discord.ui.TextInput(
        label="Cookie HoYoLAB (ltuid_v2 & ltoken_v2)",
        style=discord.TextStyle.paragraph,
        placeholder="Dan toan bo chuoi cookie lay tu trang hoyolab.com...",
        required=True,
        min_length=20,
        max_length=2000,
    )
    uid = discord.ui.TextInput(
        label="UID Game Genshin Impact",
        placeholder="VD: 812345678",
        required=True,
        min_length=9,
        max_length=10,
    )
    server = discord.ui.TextInput(
        label="May Chu (Server)",
        placeholder="os_asia, os_usa, os_euro, os_cht",
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
                title="Lien Ket Tai Khoan Genshin Thanh Cong",
                description="Tai khoan HoYoLAB cua ban da duoc ma hoa bao mat (AES-256-CBC) vao he thong.",
                color=COLOR_GREEN,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=GENSHIN_LOGO_URL)
            embed.add_field(name="Ten Nhan Vat", value=f"**{res.get('nickname')}**", inline=True)
            embed.add_field(name="UID Game", value=f"`{res.get('uid')}`", inline=True)
            embed.add_field(name="May Chu", value=f"`{res.get('server').upper()}`", inline=True)
            embed.add_field(
                name="Trang Thai Tu Dong",
                value="- Tu dong diem danh: Bat\n- Tu dong nhan Giftcode: San sang\n- Theo doi Nhua thoi gian thuc: San sang",
                inline=False,
            )
            embed.set_footer(text="Elyriax Genshin System")

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Genshin link modal error: {e}")
            await interaction.followup.send(f"Loi lien ket: {str(e)}", ephemeral=True)


class LinkOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        oauth_url = (
            f"https://discord.com/oauth2/authorize?client_id={settings.DISCORD_CLIENT_ID}"
            f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/discord/callback')}"
            f"&response_type=code&scope=identify+email&state=login"
        )
        self.add_item(
            discord.ui.Button(
                label="Dang Nhap Elyriax",
                url=oauth_url,
                style=discord.ButtonStyle.link,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Website Elyriax",
                url=settings.FRONTEND_URL,
                style=discord.ButtonStyle.link,
            )
        )

    @discord.ui.button(label="Nhap Cookie HoYoLAB", style=discord.ButtonStyle.primary)
    async def enter_cookie_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GenshinLinkModal())


class GenshinCog(commands.Cog, name="Genshin Impact"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    genshin_group = app_commands.Group(name="genshin", description="Tien ich va tu dong hoa Genshin Impact")

    # ----------------------------------------------------
    # 1. /genshin codes
    # ----------------------------------------------------
    @genshin_group.command(name="codes", description="Tra cuu toan bo giftcode Genshin Impact moi nhat")
    async def genshin_codes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cards = await get_all_codes()
            if not cards:
                await interaction.followup.send("Hien khong co giftcode nao kha dung.")
                return

            embed = discord.Embed(
                title="Danh Sach Giftcode Genshin Impact",
                description=(
                    f"Tim thay {len(cards)} ma qua tang kha dung tu Fandom Wiki.\n"
                    "Dung /genshin redeem <ma> de doi qua truc tiep cho tai khoan."
                ),
                color=COLOR_GOLD,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            for idx, c in enumerate(cards[:10], start=1):
                code_str = " / ".join([f"`{code}`" for code in c.get("codes", [])])
                rewards_str = " • ".join(c.get("rewards", [])) or "Qua tang trong game"
                server_str = c.get("server", "Toan cau")
                validity_str = c.get("validity") or "Khong xac dinh"

                field_value = (
                    f"**Ma Code:** {code_str}\n"
                    f"**Phan thuong:** {rewards_str}\n"
                    f"**Khu vuc:** `{server_str}` | **Han:** *{validity_str}*"
                )
                embed.add_field(name=f"Code #{idx}", value=field_value, inline=False)

            embed.set_footer(text="Elyriax Hub - Fandom Wiki")
            await interaction.followup.send(embed=embed, view=CodesView())
        except Exception as e:
            logger.error(f"Error /genshin codes: {e}")
            await interaction.followup.send(f"Loi khi lay danh sach ma code: {e}")

    # ----------------------------------------------------
    # 2. /genshin banner
    # ----------------------------------------------------
    @genshin_group.command(name="banners", description="Xem thong tin banner nhan vat va vu khi hien tai")
    async def genshin_banners(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            banners = await get_banners()
            if not banners:
                await interaction.followup.send("Chua co du lieu banner kha dung.")
                return

            active_banner = next((b for b in banners if b.get("going_on")), banners[0])

            version = active_banner.get("version", "N/A")
            phase = active_banner.get("phase", "Phase 1")
            name = active_banner.get("name", "Event Wish")
            status = "DANG DIEN RA" if active_banner.get("going_on") else "SAP DIEN RA"

            five_stars_new = active_banner.get("5_star_featured", {}).get("new", [])
            five_stars_rerun = active_banner.get("5_star_featured", {}).get("rerun", [])
            five_stars = five_stars_new + five_stars_rerun
            four_stars = active_banner.get("4_star_featured", [])
            weapons = active_banner.get("weapon_banner", [])

            start_date = active_banner.get("start_date", "").replace("T", " ").replace("Z", "")
            end_date = active_banner.get("end_date", "").replace("T", " ").replace("Z", "")

            embed = discord.Embed(
                title=f"Cau Nguyen Genshin Impact - Phien Ban {version} ({phase})",
                description=f"**Chu de:** *{name}* | **Trang thai:** `{status}`",
                color=COLOR_PURPLE,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url="https://static.wikia.nocookie.net/gensin-impact/images/a/ab/Item_Intertwined_Fate.png")

            embed.add_field(
                name="Nhan Vat 5 Sao Rate-Up",
                value="\n".join([f"- **{c}**" for c in five_stars]) or "- Chua cong bo",
                inline=False,
            )
            embed.add_field(
                name="Nhan Vat 4 Sao Di Kem",
                value=" • ".join([f"**{c}**" for c in four_stars]) or "Chua cong bo",
                inline=False,
            )
            embed.add_field(
                name="Vu Khi 5 Sao (Than Hinh Duc Ket)",
                value="\n".join([f"- **{w.replace('_', ' ')}**" for w in weapons]) or "Chua cong bo",
                inline=False,
            )
            embed.add_field(
                name="Thoi Gian Dien Ra",
                value=f"- **Bat dau:** `{start_date} UTC`\n- **Ket thuc:** `{end_date} UTC`",
                inline=False,
            )

            embed.set_footer(text="Elyriax Genshin Tracker")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error /genshin banners: {e}")
            await interaction.followup.send(f"Loi khi tai du lieu banner: {e}")

    # ----------------------------------------------------
    # 3. /genshin checkin
    # ----------------------------------------------------
    @genshin_group.command(name="checkin", description="Diem danh HoYoLAB nhan qua hang ngay")
    async def genshin_checkin(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await check_in_daily(payload)

            claimed = res.get("claimed", False)
            title = "Diem Danh Thanh Cong" if claimed else "Hom Nay Ban Da Diem Danh Roi"
            color = COLOR_GREEN if claimed else COLOR_CYAN

            today_reward = res.get("today_reward") or {}
            tomorrow_reward = res.get("tomorrow_reward") or {}

            embed = discord.Embed(
                title=title,
                description=f"Nha Khai Pha: **{res.get('nickname')}** (UID: `{res.get('uid')}`)",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            if today_reward.get("icon"):
                embed.set_thumbnail(url=today_reward["icon"])
            else:
                embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            embed.add_field(name="May Chu", value=f"`{res.get('server')}`", inline=True)
            embed.add_field(name="Cap Tham Hiem (AR)", value=f"`AR {res.get('adventure_rank', 'N/A')}`", inline=True)
            embed.add_field(
                name="Tien Do Diem Danh",
                value=f"`{res.get('signed_days')}/{res.get('total_days_month')}` ngay",
                inline=True,
            )

            if today_reward:
                embed.add_field(
                    name="Phan Thuong Hom Nay",
                    value=f"**{today_reward.get('name')}** x `{today_reward.get('count')}`",
                    inline=False,
                )

            if tomorrow_reward:
                embed.add_field(
                    name="Phan Thuong Ngay Mai",
                    value=f"**{tomorrow_reward.get('name')}** x `{tomorrow_reward.get('count')}`",
                    inline=False,
                )

            embed.set_footer(text="Elyriax Auto-Checkin")
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin checkin: {e}")
            await interaction.followup.send(f"That bai khi diem danh: {e}")

    # ----------------------------------------------------
    # 4. /genshin daily_note
    # ----------------------------------------------------
    @genshin_group.command(name="daily_note", description="Kiem tra Nhua nguyen ban, Uy thac, Boss tuan va Tham hiem")
    async def genshin_daily_note(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await get_daily_note(payload)

            if not res.get("ok"):
                await interaction.followup.send(f"Khong the tai Daily Note: {res.get('error')}")
                return

            data = res["data"]
            resin = data.get("resin", {})
            tasks = data.get("daily_tasks", {})
            expeditions = data.get("expeditions", {})
            home_coin = data.get("home_coin", {})
            transformer = data.get("transformer", {})

            cur_resin = resin.get("current", 0)
            max_resin = resin.get("max", 200)
            full_time = resin.get("estimated_full_time", "Da day")

            embed = discord.Embed(
                title="Genshin Impact - Daily Note",
                description="Bao cao tai nguyen thoi gian thuc:",
                color=COLOR_CYAN,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=RESIN_ICON_URL)

            resin_bar = make_progress_bar(cur_resin, max_resin, 12)
            embed.add_field(
                name="Nhua Nguyen Ban (Original Resin)",
                value=f"{resin_bar}\n- Thoi gian hoi day: `{full_time}`",
                inline=False,
            )

            task_fin = tasks.get("finished_num", 0)
            task_total = tasks.get("total_num", 4)
            extra_claimed = "Da nhan" if tasks.get("is_extra_reward_received") else "Chua nhan"
            task_bar = make_progress_bar(task_fin, task_total, 8)
            embed.add_field(
                name="Nhiem Vu Uy Thac",
                value=f"{task_bar}\n- Thuong Katherine: {extra_claimed}",
                inline=True,
            )

            remain_boss = resin.get("resin_discount", {}).get("remain_num", 0)
            limit_boss = resin.get("resin_discount", {}).get("limit_num", 3)
            embed.add_field(
                name="Giam Nua Nhua Boss Tuan",
                value=f"`{remain_boss}/{limit_boss}` luot con lai",
                inline=True,
            )

            coin_cur = home_coin.get("current", 0)
            coin_max = home_coin.get("max", 2400)
            coin_full = home_coin.get("estimated_full_time", "Da day")
            coin_bar = make_progress_bar(coin_cur, coin_max, 8)
            embed.add_field(
                name="Tien Dong Tien (Serenitea Pot)",
                value=f"{coin_bar}\n- Day luc: `{coin_full}`",
                inline=True,
            )

            exp_list = expeditions.get("list", [])
            exp_lines = []
            for idx, exp in enumerate(exp_list, 1):
                st = "Hoan thanh" if exp.get("status") == "Finished" else f"{exp.get('estimated_finished_time')}"
                exp_lines.append(f"- Slot {idx}: {st}")

            embed.add_field(
                name=f"Phai Di Tham Hiem ({expeditions.get('current_num')}/{expeditions.get('max_num')})",
                value="\n".join(exp_lines) or "Khong co nhan vat nao phai di.",
                inline=True,
            )

            trans_ready = "San sang su dung" if transformer.get("ready") else "Dang hoi lai"
            embed.add_field(name="May Bien Doi Chat Luong", value=trans_ready, inline=True)

            embed.set_footer(text="Elyriax Daily Monitor")
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin daily_note: {e}")
            await interaction.followup.send(f"Loi khi tai Daily Note: {e}")

    # ----------------------------------------------------
    # 5. /genshin stats
    # ----------------------------------------------------
    @genshin_group.command(name="stats", description="Xem chien tich tai khoan: AR, ngay choi, thanh tuu, ruong va than dong")
    async def genshin_stats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            res = await get_role_and_stats(payload)

            if not res.get("ok"):
                await interaction.followup.send(f"Khong the tai chien tich: {res.get('message')}")
                return

            role = res.get("role", {})
            stats = res.get("stats", {})
            chests = stats.get("chests", {})
            oculus = stats.get("oculus", {})

            embed = discord.Embed(
                title="Chien Tich Tai Khoan Genshin Impact",
                description=f"Nha Kham Pha: **{role.get('nickname')}** | **Cap Tham Hiem (AR):** `{role.get('level')}`",
                color=COLOR_PINK,
                timestamp=datetime.now(timezone.utc),
            )
            if role.get("avatar_url"):
                embed.set_thumbnail(url=role["avatar_url"])
            else:
                embed.set_thumbnail(url=GENSHIN_LOGO_URL)

            embed.add_field(name="Ngay Hoat Dong", value=f"`{stats.get('active_days', 0)}` ngay", inline=True)
            embed.add_field(name="Thanh Tuu Dat Duoc", value=f"`{stats.get('achievements', 0)}` cai", inline=True)
            embed.add_field(name="So Nhan Vat", value=f"`{stats.get('avatars_count', 0)}`", inline=True)
            embed.add_field(name="La Hoan Tham Canh", value=f"`{stats.get('spiral_abyss', 'Chua vao')}`", inline=True)
            embed.add_field(name="Diem Dich Chuyen", value=f"`{stats.get('way_points', 0)}`", inline=True)
            embed.add_field(name="Bi Canh Da Mo", value=f"`{stats.get('domains', 0)}`", inline=True)

            chests_text = (
                f"- Thuong: `{chests.get('common', 0)}`\n"
                f"- Cao Cap: `{chests.get('exquisite', 0)}`\n"
                f"- Hiem: `{chests.get('precious', 0)}`\n"
                f"- Sieu Cap: `{chests.get('luxurious', 0)}`"
            )
            embed.add_field(name="Thong Ke Mo Ruong", value=chests_text, inline=True)

            oculus_text = (
                f"- Phong: `{oculus.get('anemo', 0)}` | Nham: `{oculus.get('geo', 0)}`\n"
                f"- Loi: `{oculus.get('electro', 0)}` | Thao: `{oculus.get('dendro', 0)}`\n"
                f"- Thuy: `{oculus.get('hydro', 0)}` | Hoa: `{oculus.get('pyro', 0)}`"
            )
            embed.add_field(name="Than Dong Thu Thap", value=oculus_text, inline=True)

            embed.set_footer(text="Elyriax Battle Chronicle")
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin stats: {e}")
            await interaction.followup.send(f"Loi khi tai chien tich: {e}")

    # ----------------------------------------------------
    # 6. /genshin redeem <code>
    # ----------------------------------------------------
    @genshin_group.command(name="redeem", description="Doi giftcode nhan qua truc tiep cho tai khoan Genshin")
    @app_commands.describe(code="Ma giftcode can doi (VD: GENSHINGIFT)")
    async def genshin_redeem(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer()
        try:
            payload = await get_user_genshin_payload(interaction.user)
            payload["code"] = code.strip().upper()

            res = await redeem_code(payload)
            ok = res.get("ok", False)
            title = "Nhap Ma Giftcode Thanh Cong" if ok else "Nhap Ma Khong Thanh Cong"
            color = COLOR_GREEN if ok else COLOR_RED

            embed = discord.Embed(
                title=title,
                description=f"**Ma qua tang:** `{code.strip().upper()}`\n**Thong bao he thong:** {res.get('message') or res.get('error')}",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=PRIMOGEM_ICON_URL)

            rewards = res.get("rewards", [])
            if rewards:
                embed.add_field(name="Phan Thuong Nhan Duoc", value=" • ".join(rewards), inline=False)

            if res.get("uid"):
                embed.add_field(name="UID Nhan", value=f"`{res.get('uid')}`", inline=True)
                embed.add_field(name="Server", value=f"`{res.get('server')}`", inline=True)

            embed.set_footer(text="Elyriax Code Redemption")
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(str(ve))
        except Exception as e:
            logger.error(f"Error /genshin redeem: {e}")
            await interaction.followup.send(f"That bai khi doi code: {e}")

    # ----------------------------------------------------
    # 7. /genshin link
    # ----------------------------------------------------
    @genshin_group.command(name="link", description="Lien ket tai khoan Genshin Impact (Nhap cookie hoac qua Elyriax)")
    async def genshin_link(self, interaction: discord.Interaction):
        oauth = await fetch_one(
            "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
            (str(interaction.user.id),),
        )
        sync_status = "Da lien ket voi Elyriax.com" if oauth else "Chua lien ket voi Elyriax.com"

        embed = discord.Embed(
            title="Lien Ket Tai Khoan Genshin Impact",
            description=(
                f"**Trang thai ket noi:** `{sync_status}`\n\n"
                "Chon phuong thuc lien ket phu hop:\n\n"
                "**1. Nhap Cookie HoYoLAB Truc Tiep (Dung cho Bot Discord):**\n"
                "Nhan nut **[Nhap Cookie HoYoLAB]** ben duoi de mo form dien Cookie (ltuid_v2, ltoken_v2), UID va Server. Du lieu duoc ma hoa AES-256-CBC.\n\n"
                "**2. Lien Ket Voi Tai Khoan Elyriax.com:**\n"
                "Su dung lenh `/auth link` de lien ket tai khoan Discord nay voi tai khoan tren web Elyriax.com cua ban."
            ),
            color=COLOR_CYAN,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=GENSHIN_LOGO_URL)
        embed.set_footer(text="Elyriax Genshin System")

        await interaction.response.send_message(embed=embed, view=LinkOptionsView(), ephemeral=True)

    # ----------------------------------------------------
    # 8. /genshin accounts
    # ----------------------------------------------------
    @genshin_group.command(name="accounts", description="Xem danh sach cac tai khoan Genshin da lien ket")
    async def genshin_accounts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                await interaction.followup.send(
                    "Ban chua lien ket tai khoan nao. Hay dung `/genshin link` de them tai khoan.",
                    ephemeral=True,
                )
                return

            accounts = await get_accounts(oauth["user_id"])
            if not accounts:
                await interaction.followup.send(
                    "Ban chua co tai khoan Genshin nao. Hay dung `/genshin link` de lien ket.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="Danh Sach Tai Khoan Genshin Da Lien Ket",
                description=f"Tim thay {len(accounts)} tai khoan cua **{interaction.user.display_name}**:",
                color=COLOR_BLUE,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=GENSHIN_LOGO_URL)

            for acc in accounts:
                is_def = "[Mac dinh]" if acc.get("is_default") else ""
                checkin_status = "Bat" if acc.get("auto_checkin") else "Tat"
                val = (
                    f"- **UID:** `{acc.get('uid')}`\n"
                    f"- **May chu:** `{acc.get('server', '').upper()}`\n"
                    f"- **Auto Check-in:** {checkin_status}\n"
                    f"- **Account ID:** `{acc.get('id')}`"
                )
                embed.add_field(name=f"{acc.get('nickname', 'Nha Khai Pha')} {is_def}".strip(), value=val, inline=False)

            embed.set_footer(text="Dung /genshin switch <id> de doi tai khoan mac dinh")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error /genshin accounts: {e}")
            await interaction.followup.send(f"Loi: {e}", ephemeral=True)

    # ----------------------------------------------------
    # 9. /genshin switch <account_id>
    # ----------------------------------------------------
    @genshin_group.command(name="switch", description="Dat tai khoan Genshin lam tai khoan mac dinh")
    @app_commands.describe(account_id="ID tai khoan trong lenh /genshin accounts")
    async def genshin_switch(self, interaction: discord.Interaction, account_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT user_id FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                await interaction.followup.send("Ban chua lien ket tai khoan nao.", ephemeral=True)
                return

            await update_account(oauth["user_id"], account_id, {"is_default": True})
            await interaction.followup.send(
                f"Da dat tai khoan ID `{account_id}` lam tai khoan mac dinh thanh cong.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error /genshin switch: {e}")
            await interaction.followup.send(f"Loi khi chuyen tai khoan: {e}", ephemeral=True)

    # ----------------------------------------------------
    # 10. /genshin sync
    # ----------------------------------------------------
    @genshin_group.command(name="sync", description="Kiem tra trang thai lien ket va dong bo voi Elyriax.com")
    async def genshin_sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT * FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                embed = discord.Embed(
                    title="Tai Khoan Discord Chua Dong Bo Voi Elyriax",
                    description=(
                        f"Tai khoan Discord **{interaction.user.display_name}** chua duoc lien ket voi tai khoan tren **Elyriax.com**.\n\n"
                        "- De lien ket tai khoan web san co cua ban, su dung lenh `/auth link`.\n"
                        "- De them tai khoan Genshin bang Cookie HoYoLAB, su dung lenh `/genshin link`."
                    ),
                    color=COLOR_GOLD,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_thumbnail(url=GENSHIN_LOGO_URL)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            user_id = oauth["user_id"]
            user = await fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
            accounts = await get_accounts(user_id)

            embed = discord.Embed(
                title="Tai Khoan Da Duoc Dong Bo Voi Elyriax.com",
                description=f"Tai khoan Discord **{interaction.user.display_name}** da duoc ket noi voi he thong Elyriax.",
                color=COLOR_GREEN,
                timestamp=datetime.now(timezone.utc),
            )
            if interaction.user.display_avatar:
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
            else:
                embed.set_thumbnail(url=GENSHIN_LOGO_URL)

            embed.add_field(name="Elyriax User ID", value=f"#{user_id}", inline=True)
            embed.add_field(name="Ten Tai Khoan Web", value=user.get("username", "N/A") if user else "N/A", inline=True)
            embed.add_field(name="So Tai Khoan Genshin", value=f"{len(accounts)} tai khoan", inline=True)
            embed.add_field(
                name="Quan Ly Tren Website",
                value=f"Quan ly tai khoan va san pham tai [{settings.FRONTEND_URL}]({settings.FRONTEND_URL}).",
                inline=False,
            )
            embed.set_footer(text="Elyriax Sync Service")

            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Mo Website Elyriax",
                    url=settings.FRONTEND_URL,
                    style=discord.ButtonStyle.link,
                )
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error /genshin sync: {e}")
            await interaction.followup.send(f"Loi kiem tra dong bo: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GenshinCog(bot))
