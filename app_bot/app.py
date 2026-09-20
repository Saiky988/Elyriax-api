import logging
from pathlib import Path
import discord
from discord.ext import commands

logger = logging.getLogger("DiscordBot")


class UniversalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
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

        # Đồng bộ Slash Commands toàn cầu
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Bot connected as: {self.user} (ID: {self.user.id})")


bot = UniversalBot()
