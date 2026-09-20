import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from app_bot.services.guild_settings import (
    build_leave_embed,
    build_welcome_embed,
    format_placeholders,
    get_guild_settings,
    update_guild_settings,
)

logger = logging.getLogger("GuildManage")


def check_admin_perm(interaction: discord.Interaction) -> bool:
    """Kiểm tra quyền Manage Guild hoặc Administrator của người dùng."""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    perms = interaction.user.guild_permissions
    return perms.manage_guild or perms.administrator


class GuildManageCog(commands.Cog, name="GuildManagement"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----------------------------------------------------
    # Event Listeners: Member Join & Member Leave
    # ----------------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Xử lý sự kiện khi có thành viên mới gia nhập máy chủ."""
        if member.bot:
            return

        guild = member.guild
        cfg = get_guild_settings(guild.id)

        # 1. Tự động cấp Auto Role (nếu bật)
        if cfg.get("autorole_enabled") and cfg.get("autorole_id"):
            role_id = cfg.get("autorole_id")
            role = guild.get_role(role_id)
            if role and guild.me.guild_permissions.manage_roles:
                try:
                    if role < guild.me.top_role:
                        await member.add_roles(role, reason="Elyriax Auto-Role khi gia nhập máy chủ")
                    else:
                        logger.warning(f"Role {role.name} nằm cao hơn vai trò cao nhất của Bot trong {guild.name}")
                except Exception as e:
                    logger.error(f"Lỗi khi cấp auto role cho {member.name}: {e}")

        # 2. Gửi tin nhắn chào mừng (nếu bật)
        if cfg.get("welcome_enabled") and cfg.get("welcome_channel_id"):
            channel_id = cfg.get("welcome_channel_id")
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                perms = channel.permissions_for(guild.me)
                if perms.send_messages:
                    try:
                        if cfg.get("welcome_embed", True):
                            embed = build_welcome_embed(member, cfg)
                            await channel.send(content=member.mention, embed=embed)
                        else:
                            msg = format_placeholders(cfg.get("welcome_message", ""), member, guild)
                            await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Lỗi khi gửi tin nhắn welcome tại {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Xử lý sự kiện khi có thành viên rời khỏi máy chủ."""
        if member.bot:
            return

        guild = member.guild
        cfg = get_guild_settings(guild.id)

        # Gửi thông báo thành viên rời đi (nếu bật)
        if cfg.get("leave_enabled") and cfg.get("leave_channel_id"):
            channel_id = cfg.get("leave_channel_id")
            channel = guild.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                perms = channel.permissions_for(guild.me)
                if perms.send_messages:
                    try:
                        if cfg.get("leave_embed", True):
                            embed = build_leave_embed(member, cfg)
                            await channel.send(embed=embed)
                        else:
                            msg = format_placeholders(cfg.get("leave_message", ""), member, guild)
                            await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Lỗi khi gửi thông báo leave tại {guild.name}: {e}")

    # ----------------------------------------------------
    # Group: /setup
    # ----------------------------------------------------
    setup_group = app_commands.Group(
        name="setup",
        description="Quản lý và cấu hình máy chủ (Welcome, Leave, AutoRole)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @setup_group.command(name="view", description="Xem toàn bộ cấu hình hiện tại của máy chủ")
    async def setup_view(self, interaction: discord.Interaction):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        guild = interaction.guild
        cfg = get_guild_settings(guild.id)

        w_status = "ĐANG BẬT" if cfg.get("welcome_enabled") else "ĐÃ TẮT"
        w_ch = f"<#{cfg.get('welcome_channel_id')}>" if cfg.get("welcome_channel_id") else "*Chưa thiết lập*"
        w_mode = "Embed Chuyên Nghiệp" if cfg.get("welcome_embed") else "Văn Bản Thường"

        l_status = "ĐANG BẬT" if cfg.get("leave_enabled") else "ĐÃ TẮT"
        l_ch = f"<#{cfg.get('leave_channel_id')}>" if cfg.get("leave_channel_id") else "*Chưa thiết lập*"
        l_mode = "Embed Chuyên Nghiệp" if cfg.get("leave_embed") else "Văn Bản Thường"

        ar_status = "ĐANG BẬT" if cfg.get("autorole_enabled") else "ĐÃ TẮT"
        ar_role = f"<@&{cfg.get('autorole_id')}>" if cfg.get("autorole_id") else "*Chưa thiết lập*"

        embed = discord.Embed(
            title=f"BẢNG CẤU HÌNH MÁY CHỦ • {guild.name.upper()}",
            description="Tổng hợp trạng thái các tính năng tự động hóa trên server.",
            color=0x38BDF8,
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(
            name="Hệ Thống Chào Mừng (Welcome)",
            value=(
                f"• **Trạng thái:** `{w_status}`\n"
                f"• **Kênh gửi:** {w_ch}\n"
                f"• **Định dạng:** `{w_mode}`\n"
                f"• **Lời chào:** {cfg.get('welcome_message')}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Hệ Thống Tạm Biệt (Leave)",
            value=(
                f"• **Trạng thái:** `{l_status}`\n"
                f"• **Kênh gửi:** {l_ch}\n"
                f"• **Định dạng:** `{l_mode}`\n"
                f"• **Lời tạm biệt:** {cfg.get('leave_message')}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Tự Động Cấp Vai Trò (Auto-Role)",
            value=(
                f"• **Trạng thái:** `{ar_status}`\n"
                f"• **Vai trò cấp:** {ar_role}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Các biến động hỗ trợ",
            value="`{user}`: Tag người dùng | `{user_name}`: Tên hiển thị | `{server}`: Tên server | `{member_count}`: Số thành viên",
            inline=False,
        )

        embed.set_footer(text="Sử dụng /setup welcome, /setup leave hoặc /setup autorole để tùy chỉnh")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_group.command(name="welcome", description="Cấu hình hệ thống chào mừng thành viên mới")
    @app_commands.describe(
        channel="Kênh văn bản sẽ gửi thông báo chào mừng",
        enabled="Bật hoặc tắt tính năng",
        use_embed="Sử dụng khung Embed chuyên nghiệp (True) hay tin nhắn thường (False)",
        message="Nội dung lời chào (dùng {user}, {server}, {member_count}...)"
    )
    async def setup_welcome(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        enabled: Optional[bool] = True,
        use_embed: Optional[bool] = True,
        message: Optional[str] = None,
    ):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        updates = {
            "welcome_channel_id": channel.id,
            "welcome_enabled": enabled,
            "welcome_embed": use_embed,
        }
        if message:
            updates["welcome_message"] = message

        update_guild_settings(interaction.guild_id, updates)

        status_text = "Đã bật" if enabled else "Đã tắt"
        embed = discord.Embed(
            title="CẬP NHẬT WELCOME THÀNH CÔNG",
            description=f"Hệ thống chào mừng đã được cấu hình cho kênh {channel.mention}.",
            color=0x10B981,
        )
        embed.add_field(name="Trạng thái", value=f"`{status_text}`", inline=True)
        embed.add_field(name="Định dạng", value=f"`{'Embed' if use_embed else 'Văn bản'}`", inline=True)
        if message:
            embed.add_field(name="Nội dung lời chào", value=message, inline=False)
        embed.set_footer(text="Bạn có thể gõ /welcome test để kiểm tra ngay giao diện hiển thị")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_group.command(name="leave", description="Cấu hình hệ thống thông báo khi có thành viên rời máy chủ")
    @app_commands.describe(
        channel="Kênh văn bản sẽ gửi thông báo rời đi",
        enabled="Bật hoặc tắt tính năng",
        use_embed="Sử dụng khung Embed chuyên nghiệp (True) hay tin nhắn thường (False)",
        message="Nội dung lời tạm biệt (dùng {user_name}, {server}...)"
    )
    async def setup_leave(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        enabled: Optional[bool] = True,
        use_embed: Optional[bool] = True,
        message: Optional[str] = None,
    ):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        updates = {
            "leave_channel_id": channel.id,
            "leave_enabled": enabled,
            "leave_embed": use_embed,
        }
        if message:
            updates["leave_message"] = message

        update_guild_settings(interaction.guild_id, updates)

        status_text = "Đã bật" if enabled else "Đã tắt"
        embed = discord.Embed(
            title="CẬP NHẬT LEAVE THÀNH CÔNG",
            description=f"Hệ thống thông báo rời máy chủ đã được cấu hình cho kênh {channel.mention}.",
            color=0x10B981,
        )
        embed.add_field(name="Trạng thái", value=f"`{status_text}`", inline=True)
        embed.add_field(name="Định dạng", value=f"`{'Embed' if use_embed else 'Văn bản'}`", inline=True)
        if message:
            embed.add_field(name="Nội dung lời tạm biệt", value=message, inline=False)
        embed.set_footer(text="Bạn có thể gõ /leave test để kiểm tra ngay giao diện hiển thị")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_group.command(name="autorole", description="Cấu hình vai trò tự động cấp khi thành viên mới vào server")
    @app_commands.describe(
        role="Vai trò (Role) sẽ tự động cấp",
        enabled="Bật hoặc tắt tính năng auto role"
    )
    async def setup_autorole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        enabled: Optional[bool] = True,
    ):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        # Kiểm tra vị trí role so với bot
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"Vai trò {role.mention} nằm cao hơn hoặc bằng vị trí vai trò của Bot. "
                "Vui lòng kéo vai trò của Bot lên cao hơn trong Server Settings để có thể cấp role này!",
                ephemeral=True,
            )
            return

        updates = {
            "autorole_id": role.id,
            "autorole_enabled": enabled,
        }
        update_guild_settings(interaction.guild_id, updates)

        status_text = "Đang bật" if enabled else "Đã tắt"
        embed = discord.Embed(
            title="CẤU HÌNH AUTO-ROLE THÀNH CÔNG",
            description=f"Thành viên mới gia nhập máy chủ sẽ được cấp vai trò {role.mention}.",
            color=0x10B981,
        )
        embed.add_field(name="Trạng thái", value=f"`{status_text}`", inline=True)
        embed.add_field(name="Vai trò", value=role.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setup_group.command(name="reset", description="Khôi phục toàn bộ cấu hình máy chủ về mặc định")
    async def setup_reset(self, interaction: discord.Interaction):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        from app_bot.services.guild_settings import DEFAULT_GUILD_CONFIG
        update_guild_settings(interaction.guild_id, dict(DEFAULT_GUILD_CONFIG))

        embed = discord.Embed(
            title="ĐÃ KHÔI PHỤC MẶC ĐỊNH",
            description="Toàn bộ cài đặt Welcome, Leave và Auto-Role của máy chủ đã được đặt lại ban đầu.",
            color=0x38BDF8,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----------------------------------------------------
    # Group: /welcome
    # ----------------------------------------------------
    welcome_group = app_commands.Group(
        name="welcome",
        description="Lệnh điều khiển nhanh tính năng chào mừng thành viên mới",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @welcome_group.command(name="test", description="Gửi tin nhắn chào mừng thử nghiệm để xem trước")
    async def welcome_test(self, interaction: discord.Interaction):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        cfg = get_guild_settings(interaction.guild_id)
        if cfg.get("welcome_embed", True):
            embed = build_welcome_embed(interaction.user, cfg)
            await interaction.response.send_message(
                content=f"*(Bản xem trước test welcome)*\n{interaction.user.mention}",
                embed=embed,
                ephemeral=False,
            )
        else:
            msg = format_placeholders(cfg.get("welcome_message", ""), interaction.user, interaction.guild)
            await interaction.response.send_message(f"*(Bản xem trước test welcome)*\n{msg}", ephemeral=False)

    @welcome_group.command(name="channel", description="Thiết lập nhanh kênh gửi tin nhắn chào mừng")
    @app_commands.describe(channel="Kênh văn bản muốn đặt làm nơi chào mừng")
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"welcome_channel_id": channel.id, "welcome_enabled": True})
        await interaction.response.send_message(
            f"Đã đặt kênh chào mừng thành viên mới tại {channel.mention} và bật tính năng!",
            ephemeral=True,
        )

    @welcome_group.command(name="message", description="Tùy chỉnh nội dung lời chào mừng")
    @app_commands.describe(message="Nội dung lời chào (dùng {user}, {server}, {member_count}, {created_at}...)")
    async def welcome_message(self, interaction: discord.Interaction, message: str):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"welcome_message": message})
        await interaction.response.send_message(
            f"Đã cập nhật lời chào mừng thành:\n> {message}\n*(Bạn có thể gõ `/welcome test` để xem thử)*",
            ephemeral=True,
        )

    @welcome_group.command(name="toggle", description="Bật hoặc tắt tính năng chào mừng")
    @app_commands.describe(enabled="True: Bật | False: Tắt")
    async def welcome_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"welcome_enabled": enabled})
        status_text = "BẬT" if enabled else "TẮT"
        await interaction.response.send_message(f"Đã **{status_text}** hệ thống chào mừng thành viên mới.", ephemeral=True)

    @welcome_group.command(name="embed", description="Bật hoặc tắt giao diện Embed cho lời chào")
    @app_commands.describe(use_embed="True: Dùng Embed chuyên nghiệp | False: Dùng tin nhắn văn bản thuần")
    async def welcome_embed(self, interaction: discord.Interaction, use_embed: bool):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"welcome_embed": use_embed})
        mode_text = "Embed chuyên nghiệp" if use_embed else "Tin nhắn văn bản thuần"
        await interaction.response.send_message(f"Đã đổi định dạng thông báo chào mừng sang: **{mode_text}**.", ephemeral=True)

    # ----------------------------------------------------
    # Group: /leave
    # ----------------------------------------------------
    leave_group = app_commands.Group(
        name="leave",
        description="Lệnh điều khiển nhanh tính năng thông báo thành viên rời máy chủ",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @leave_group.command(name="test", description="Gửi tin nhắn tạm biệt thử nghiệm để xem trước")
    async def leave_test(self, interaction: discord.Interaction):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        cfg = get_guild_settings(interaction.guild_id)
        if cfg.get("leave_embed", True):
            embed = build_leave_embed(interaction.user, cfg)
            await interaction.response.send_message(
                content="*(Bản xem trước test leave)*",
                embed=embed,
                ephemeral=False,
            )
        else:
            msg = format_placeholders(cfg.get("leave_message", ""), interaction.user, interaction.guild)
            await interaction.response.send_message(f"*(Bản xem trước test leave)*\n{msg}", ephemeral=False)

    @leave_group.command(name="channel", description="Thiết lập nhanh kênh thông báo thành viên rời đi")
    @app_commands.describe(channel="Kênh văn bản muốn đặt làm nơi thông báo")
    async def leave_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"leave_channel_id": channel.id, "leave_enabled": True})
        await interaction.response.send_message(
            f"Đã đặt kênh thông báo rời máy chủ tại {channel.mention} và bật tính năng!",
            ephemeral=True,
        )

    @leave_group.command(name="message", description="Tùy chỉnh nội dung lời tạm biệt")
    @app_commands.describe(message="Nội dung lời tạm biệt (dùng {user_name}, {server}, {member_count}...)")
    async def leave_message(self, interaction: discord.Interaction, message: str):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"leave_message": message})
        await interaction.response.send_message(
            f"Đã cập nhật lời tạm biệt thành:\n> {message}\n*(Bạn có thể gõ `/leave test` để xem thử)*",
            ephemeral=True,
        )

    @leave_group.command(name="toggle", description="Bật hoặc tắt thông báo rời máy chủ")
    @app_commands.describe(enabled="True: Bật | False: Tắt")
    async def leave_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"leave_enabled": enabled})
        status_text = "BẬT" if enabled else "TẮT"
        await interaction.response.send_message(f"Đã **{status_text}** thông báo thành viên rời máy chủ.", ephemeral=True)

    @leave_group.command(name="embed", description="Bật hoặc tắt giao diện Embed cho lời tạm biệt")
    @app_commands.describe(use_embed="True: Dùng Embed chuyên nghiệp | False: Dùng tin nhắn văn bản thuần")
    async def leave_embed(self, interaction: discord.Interaction, use_embed: bool):
        if not check_admin_perm(interaction):
            await interaction.response.send_message("Bạn cần quyền **Quản Lý Máy Chủ** để dùng lệnh này.", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, {"leave_embed": use_embed})
        mode_text = "Embed chuyên nghiệp" if use_embed else "Tin nhắn văn bản thuần"
        await interaction.response.send_message(f"Đã đổi định dạng thông báo rời đi sang: **{mode_text}**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildManageCog(bot))
