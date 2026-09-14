import logging
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
import jwt

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one

logger = logging.getLogger("Command_Auth")

COLOR_DEFAULT = 0x2563EB
COLOR_SUCCESS = 0x10B981
COLOR_ERROR = 0xEF4444


class AuthLinkModal(discord.ui.Modal, title="Lien Ket Tai Khoan Elyriax"):
    token = discord.ui.TextInput(
        label="JWT Token hoac API Key",
        style=discord.TextStyle.paragraph,
        placeholder="Dan token hoac API Key cua ban tu elyriax.com vao day...",
        required=True,
        min_length=10,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        token_str = self.token.value.strip()
        user_id = None

        try:
            decoded = jwt.decode(token_str, settings.JWT_SECRET, algorithms=["HS256"])
            user_id = decoded.get("id")
        except Exception:
            ak = await fetch_one("SELECT user_id FROM api_keys WHERE api_key = %s", (token_str,))
            if ak:
                user_id = ak["user_id"]

        if not user_id:
            await interaction.followup.send("Token hoac API Key khong hop le hoac da het han.", ephemeral=True)
            return

        target_user = await fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
        if not target_user:
            await interaction.followup.send("Khong tim thay nguoi dung tren he thong.", ephemeral=True)
            return

        discord_id = str(interaction.user.id)
        display_name = interaction.user.display_name or interaction.user.name
        avatar_url = interaction.user.display_avatar.url if interaction.user.display_avatar else None

        existing_oauth = await fetch_one(
            "SELECT * FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
            (discord_id,),
        )

        if existing_oauth:
            if existing_oauth["user_id"] == user_id:
                await interaction.followup.send("Tai khoan Discord nay da duoc lien ket voi tai khoan cua ban tu truoc.", ephemeral=True)
                return
            await execute(
                "UPDATE user_oauth_accounts SET user_id = %s, provider_name = %s, provider_avatar = %s WHERE id = %s",
                (user_id, display_name, avatar_url, existing_oauth["id"]),
            )
        else:
            await execute(
                """
                INSERT INTO user_oauth_accounts 
                (user_id, provider, provider_user_id, provider_name, provider_avatar) 
                VALUES (%s, 'discord', %s, %s, %s)
                """,
                (user_id, discord_id, display_name, avatar_url),
            )

        oauth_url = (
            f"https://discord.com/oauth2/authorize?client_id={settings.DISCORD_CLIENT_ID}"
            f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/discord/callback')}"
            f"&response_type=code&scope=identify+email&state={token_str}"
        )

        embed = discord.Embed(
            title="Lien Ket Tai Khoan Thanh Cong",
            description=f"Tai khoan Discord **{display_name}** da duoc lien ket voi tai khoan Elyriax.",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User ID", value=f"#{user_id}", inline=True)
        embed.add_field(name="Username", value=target_user.get("username", "N/A"), inline=True)
        embed.add_field(name="Email", value=target_user.get("email", "N/A"), inline=True)
        embed.set_footer(text="Elyriax Authentication")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Mo Website Elyriax", url=settings.FRONTEND_URL, style=discord.ButtonStyle.link))
        view.add_item(discord.ui.Button(label="Trang Xac Thuc OAuth", url=oauth_url, style=discord.ButtonStyle.link))

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class AuthCog(commands.Cog, name="Authentication"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    auth_group = app_commands.Group(name="auth", description="Quan ly dang nhap va lien ket tai khoan Elyriax")

    # ----------------------------------------------------
    # /auth login [provider]
    # ----------------------------------------------------
    @auth_group.command(name="login", description="Tao link dang nhap hoac dang ky tai khoan Elyriax")
    @app_commands.describe(provider="Phuong thuc dang nhap (discord, google, github)")
    @app_commands.choices(
        provider=[
            app_commands.Choice(name="Discord", value="discord"),
            app_commands.Choice(name="Google", value="google"),
            app_commands.Choice(name="GitHub", value="github"),
        ]
    )
    async def auth_login(self, interaction: discord.Interaction, provider: str):
        provider = provider.lower()
        if provider == "discord":
            oauth_url = (
                f"https://discord.com/oauth2/authorize?client_id={settings.DISCORD_CLIENT_ID}"
                f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/discord/callback')}"
                f"&response_type=code&scope=identify+email&state=login"
            )
            title = "Dang Nhap Elyriax bang Discord"
            desc = "Nhan vao nut ben duoi de dang nhap hoac tao tai khoan Elyriax bang Discord."
        elif provider == "google":
            oauth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.GOOGLE_CLIENT_ID}"
                f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/google/callback')}"
                f"&response_type=code&scope=profile+email&state=login"
            )
            title = "Dang Nhap Elyriax bang Google"
            desc = "Nhan vao nut ben duoi de dang nhap bang tai khoan Google."
        elif provider == "github":
            oauth_url = (
                f"https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}"
                f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/github/callback')}"
                f"&scope=user:email&state=login"
            )
            title = "Dang Nhap Elyriax bang GitHub"
            desc = "Nhan vao nut ben duoi de dang nhap bang tai khoan GitHub."
        else:
            await interaction.response.send_message("Phuong thuc dang nhap khong hop le.", ephemeral=True)
            return

        embed = discord.Embed(
            title=title,
            description=desc,
            color=COLOR_DEFAULT,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Elyriax Authentication")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=f"Dang Nhap {provider.capitalize()}", url=oauth_url, style=discord.ButtonStyle.link))

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ----------------------------------------------------
    # /auth link [token]
    # ----------------------------------------------------
    @auth_group.command(name="link", description="Lien ket tai khoan Discord nay voi tai khoan Elyriax san co")
    @app_commands.describe(token="JWT token hoac API Key tu trang web elyriax.com")
    async def auth_link(self, interaction: discord.Interaction, token: Optional[str] = None):
        if not token:
            await interaction.response.send_modal(AuthLinkModal())
            return

        await interaction.response.defer(ephemeral=True)
        token_str = token.strip()
        user_id = None

        try:
            decoded = jwt.decode(token_str, settings.JWT_SECRET, algorithms=["HS256"])
            user_id = decoded.get("id")
        except Exception:
            ak = await fetch_one("SELECT user_id FROM api_keys WHERE api_key = %s", (token_str,))
            if ak:
                user_id = ak["user_id"]

        if not user_id:
            await interaction.followup.send("Token hoac API Key khong hop le hoac da het han.", ephemeral=True)
            return

        target_user = await fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
        if not target_user:
            await interaction.followup.send("Khong tim thay nguoi dung tren he thong.", ephemeral=True)
            return

        discord_id = str(interaction.user.id)
        display_name = interaction.user.display_name or interaction.user.name
        avatar_url = interaction.user.display_avatar.url if interaction.user.display_avatar else None

        existing_oauth = await fetch_one(
            "SELECT * FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
            (discord_id,),
        )

        if existing_oauth:
            if existing_oauth["user_id"] == user_id:
                await interaction.followup.send("Tai khoan Discord nay da duoc lien ket voi tai khoan cua ban tu truoc.", ephemeral=True)
                return
            await execute(
                "UPDATE user_oauth_accounts SET user_id = %s, provider_name = %s, provider_avatar = %s WHERE id = %s",
                (user_id, display_name, avatar_url, existing_oauth["id"]),
            )
        else:
            await execute(
                """
                INSERT INTO user_oauth_accounts 
                (user_id, provider, provider_user_id, provider_name, provider_avatar) 
                VALUES (%s, 'discord', %s, %s, %s)
                """,
                (user_id, discord_id, display_name, avatar_url),
            )

        oauth_url = (
            f"https://discord.com/oauth2/authorize?client_id={settings.DISCORD_CLIENT_ID}"
            f"&redirect_uri={quote(f'{settings.BASE_URL}/v1/auth/discord/callback')}"
            f"&response_type=code&scope=identify+email&state={token_str}"
        )

        embed = discord.Embed(
            title="Lien Ket Tai Khoan Thanh Cong",
            description=f"Tai khoan Discord **{display_name}** da duoc lien ket voi tai khoan Elyriax.",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User ID", value=f"#{user_id}", inline=True)
        embed.add_field(name="Username", value=target_user.get("username", "N/A"), inline=True)
        embed.add_field(name="Email", value=target_user.get("email", "N/A"), inline=True)
        embed.set_footer(text="Elyriax Authentication")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Mo Website Elyriax", url=settings.FRONTEND_URL, style=discord.ButtonStyle.link))
        view.add_item(discord.ui.Button(label="Trang Xac Thuc OAuth", url=oauth_url, style=discord.ButtonStyle.link))

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ----------------------------------------------------
    # /auth me
    # ----------------------------------------------------
    @auth_group.command(name="me", description="Xem thong tin tai khoan Elyriax da lien ket voi Discord nay")
    async def auth_me(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT * FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                embed = discord.Embed(
                    title="Chua Lien Ket Tai Khoan",
                    description=(
                        f"Tai khoan Discord **{interaction.user.display_name}** chua lien ket voi Elyriax.\n\n"
                        "Su dung `/auth login` de dang nhap/tao tai khoan, hoac `/auth link` de lien ket voi tai khoan san co."
                    ),
                    color=COLOR_DEFAULT,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Elyriax Authentication")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            user_id = oauth["user_id"]
            user = await fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
            if not user:
                await interaction.followup.send("Khong tim thay du lieu tai khoan.", ephemeral=True)
                return

            all_oauth = await fetch_all("SELECT provider, provider_email FROM user_oauth_accounts WHERE user_id = %s", (user_id,))
            providers_str = ", ".join([o["provider"].capitalize() for o in all_oauth]) or "None"

            created_str = user["created_at"].strftime("%Y-%m-%d %H:%M:%S") if user.get("created_at") else "N/A"

            embed = discord.Embed(
                title="Thong Tin Tai Khoan Elyriax",
                description=f"Thong tin tai khoan Elyriax duoc lien ket voi Discord **{interaction.user.display_name}**:",
                color=COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc),
            )
            if user.get("avatar"):
                embed.set_thumbnail(url=user["avatar"])
            elif interaction.user.display_avatar:
                embed.set_thumbnail(url=interaction.user.display_avatar.url)

            embed.add_field(name="User ID", value=f"#{user_id}", inline=True)
            embed.add_field(name="Username", value=user.get("username", "N/A"), inline=True)
            embed.add_field(name="Email", value=user.get("email") or "Chua cap nhat", inline=True)
            embed.add_field(name="Phuong Thuc Lien Ket", value=providers_str, inline=True)
            embed.add_field(name="Trang Thai", value=user.get("status", "active").upper(), inline=True)
            embed.add_field(name="Ngay Tao", value=created_str, inline=True)
            embed.set_footer(text="Elyriax Authentication")

            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Mo Website Elyriax", url=settings.FRONTEND_URL, style=discord.ButtonStyle.link))

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error /auth me: {e}")
            await interaction.followup.send(f"Loi: {e}", ephemeral=True)

    # ----------------------------------------------------
    # /auth unlink
    # ----------------------------------------------------
    @auth_group.command(name="unlink", description="Huy lien ket tai khoan Discord khoi Elyriax")
    async def auth_unlink(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            oauth = await fetch_one(
                "SELECT * FROM user_oauth_accounts WHERE provider = 'discord' AND provider_user_id = %s",
                (str(interaction.user.id),),
            )
            if not oauth:
                await interaction.followup.send("Tai khoan Discord nay chua tung lien ket voi Elyriax.", ephemeral=True)
                return

            user_id = oauth["user_id"]
            links = await fetch_all("SELECT provider FROM user_oauth_accounts WHERE user_id = %s", (user_id,))
            u = await fetch_one("SELECT password_hash FROM users WHERE id = %s", (user_id,))
            has_password = (u.get("password_hash") is not None) if u else False

            if len(links) + (1 if has_password else 0) <= 1:
                await interaction.followup.send(
                    "Khong the huy lien ket: Day la phuong thuc dang nhap duy nhat cua tai khoan!",
                    ephemeral=True,
                )
                return

            await execute("DELETE FROM user_oauth_accounts WHERE id = %s", (oauth["id"],))
            await interaction.followup.send("Da huy lien ket tai khoan Discord khoi Elyriax thanh cong.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error /auth unlink: {e}")
            await interaction.followup.send(f"Loi: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuthCog(bot))
