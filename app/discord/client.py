import logging
import asyncio
import discord
from app.core.config import settings

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logger.info(f"[Discord] Logged in as: {client.user}")

async def start_discord_bot():
    token = settings.DISCORD_BOT_TOKEN
    if not token:
        logger.info("[Discord] No DISCORD_BOT_TOKEN provided, skipping bot start.")
        return
    try:
        await client.start(token)
    except Exception as e:
        logger.error(f"[Discord] Khởi động Bot thất bại: {e}")

async def close_discord_bot():
    if not client.is_closed():
        await client.close()
