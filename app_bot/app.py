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

        # Đồng bộ Slash Commands toàn cầu (Global Sync)
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} global slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync global slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Bot connected as: {self.user} (ID: {self.user.id})")
        # Đồng bộ tức thì tới tất cả các Guild mà Bot đang tham gia để lệnh hiện ngay lập tức
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced_guild = await self.tree.sync(guild=guild)
                logger.info(f"Instant synced {len(synced_guild)} slash commands to guild: {guild.name} ({guild.id})")
            except Exception as e:
                logger.error(f"Failed to sync commands to guild {guild.name} ({guild.id}): {e}")


bot = UniversalBot()
