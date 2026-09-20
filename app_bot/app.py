import logging
import os
from pathlib import Path
import discord
from discord.ext import commands

logger = logging.getLogger("DiscordBot")


class UniversalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        routes_dir = Path(__file__).resolve().parent / "routes"
        for route_file in routes_dir.glob("*.py"):
            if route_file.name != "__init__.py":
                module_name = f"app_bot.routes.{route_file.stem}"
                try:
                    await self.load_extension(module_name)
                    logger.info(f"Loaded Discord route: {module_name}")
                except Exception as e:
                    logger.error(f"Failed to load {module_name}: {e}")

        # 1. Đồng bộ Slash Commands toàn cầu (Global Sync)
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} global slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync global slash commands: {e}")

        # 2. Đồng bộ tức thì cho Guild chính (nếu có cấu hình GUILD_ID) để hiện lệnh ngay không bị delay cache của Discord
        guild_id = os.getenv("GUILD_ID")
        if guild_id and guild_id.strip():
            try:
                guild_obj = discord.Object(id=int(guild_id.strip()))
                self.tree.copy_global_to(guild=guild_obj)
                synced_guild = await self.tree.sync(guild=guild_obj)
                logger.info(f"Successfully synced {len(synced_guild)} guild slash commands for guild {guild_id}.")
            except Exception as e:
                logger.error(f"Failed to sync guild slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Bot connected as: {self.user} (ID: {self.user.id})")


bot = UniversalBot()
