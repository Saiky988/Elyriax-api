import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent))

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import socketio

from app.core.config import settings
from app.core.database import init_db_pool, close_db_pool

# Vietsub Studio Services
from app.services.job_manager import job_manager
from app_bot.app import bot

# Migrated Background Services
from app.services.profile_cache import start_profile_cache
from app.services.scheduler.index import start_schedulers

# System Realtime Stats
from app.api.v1.host import record_system_history

# Vietsub Studio Routers
from app.api.v1.downloader import router as downloader_router
from app.api.v1.transcribe import router as transcribe_router
from app.api.v1.translate import router as translate_router
from app.api.v1.subtitle import router as subtitle_router
from app.api.v1.render import router as render_router

# Migrated Elyriax API Routers
from app.api.v1.host import router as host_router
from app.api.v1.auth import router as auth_router
from app.api.v1.settings import router as settings_router
from app.api.v1.cart import router as cart_router
from app.api.v1.order import router as order_router
from app.api.v1.wishlist import router as wishlist_router
from app.api.v1.wallet import router as wallet_router
from app.api.v1.payment import router as payment_router
from app.api.v1.product import router as product_router
from app.api.v1.admin_product import router as admin_product_router
from app.api.v1.email import router as email_router
from app.api.v1.admin_scheduler import router as admin_scheduler_router
from app.api.v1.genshin import router as genshin_router
from app.api.v1.hentai import router as hentai_router
from app.api.v1.truyen import router as truyen_router
from app.api.v1.text_translate import router as text_translate_router
from app.api.v1.evn import router as evn_router
from app.api.v1.go import router as go_router
from app.api.v1.file_up import router as file_up_router

# Python Online Sandbox Router
from app.api.v1.compiler import router as compiler_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Main")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db_pool()
        logger.info("[Database] MySQL Connection Pool initialized.")
    except Exception as e:
        logger.warning(f"[Database] Could not connect to MySQL pool at startup: {e}")

    try:
        start_profile_cache()
    except Exception as e:
        logger.error(f"[ProfileCache] Start failed: {e}")

    try:
        start_schedulers()
    except Exception as e:
        logger.error(f"[Scheduler] Start failed: {e}")

    async def cleanup_loop():
        while True:
            try:
                await asyncio.sleep(3600)
                await job_manager.cleanup_expired_jobs(ttl_seconds=3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup worker: {e}")

    cleanup_task = asyncio.create_task(cleanup_loop())

    async def metrics_emitter():
        while True:
            try:
                snapshot = record_system_history(sio_server=sio)
                if snapshot:
                    await sio.emit("system_realtime_update", snapshot)
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error emitting system update: {e}")
                await asyncio.sleep(2)

    metrics_task = asyncio.create_task(metrics_emitter())

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    bot_task = None
    if bot_token:
        bot_task = asyncio.create_task(bot.start(bot_token))
    else:
        logger.warning("[Discord] DISCORD_BOT_TOKEN not found in environment.")

    yield

    cleanup_task.cancel()
    metrics_task.cancel()
    if bot_task:
        logger.info("Shutting down Discord Bot...")
        await bot.close()
        bot_task.cancel()

    try:
        await close_db_pool()
        logger.info("[Database] MySQL Connection Pool closed.")
    except Exception as e:
        logger.error(f"[Database] Error closing MySQL pool: {e}")


fastapi_app = FastAPI(
    title="Elyriax API",
    version="2.0.0",
    lifespan=lifespan
)

@fastapi_app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    request.state.start_time = time.time()
    response = await call_next(request)
    return response

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "Accept-Ranges"]
)

fastapi_app.include_router(downloader_router, prefix="/api/v1/downloader", tags=["Downloader"])
fastapi_app.include_router(transcribe_router, prefix="/api/v1", tags=["Transcription"])
fastapi_app.include_router(translate_router, prefix="/api/v1", tags=["Translation"])
fastapi_app.include_router(subtitle_router, prefix="/api/v1", tags=["Subtitles"])
fastapi_app.include_router(render_router, prefix="/api/v1", tags=["Rendering"])

fastapi_app.include_router(downloader_router, prefix="/v1/downloader", tags=["Downloader"])
fastapi_app.include_router(host_router, prefix="/v1/host", tags=["Host / System"])
fastapi_app.include_router(auth_router, prefix="/v1/auth", tags=["Auth"])
fastapi_app.include_router(settings_router, prefix="/v1/settings", tags=["Settings"])
fastapi_app.include_router(cart_router, prefix="/v1/cart", tags=["Cart"])
fastapi_app.include_router(order_router, prefix="/v1/orders", tags=["Orders"])
fastapi_app.include_router(wishlist_router, prefix="/v1/wishlist", tags=["Wishlist"])
fastapi_app.include_router(wallet_router, prefix="/v1/wallet", tags=["Wallet"])
fastapi_app.include_router(payment_router, prefix="/v1/payment", tags=["Payment"])
fastapi_app.include_router(product_router, prefix="/v1/products", tags=["Products"])
fastapi_app.include_router(admin_product_router, prefix="/v1/admin", tags=["Admin Products"])
fastapi_app.include_router(email_router, prefix="/v1/email", tags=["Email"])
fastapi_app.include_router(admin_scheduler_router, prefix="/v1/admin/scheduler", tags=["Admin Scheduler"])
fastapi_app.include_router(genshin_router, prefix="/v1/genshin", tags=["Genshin Impact"])
fastapi_app.include_router(hentai_router, prefix="/v1", tags=["Hentai"])
fastapi_app.include_router(truyen_router, prefix="/v1/truyen", tags=["Truyen"])
fastapi_app.include_router(text_translate_router, prefix="/v1/translate", tags=["Cultural Translation"])
fastapi_app.include_router(evn_router, prefix="/v1/evn", tags=["EVN Power Outage"])

# Top-level shortlinks & file download routers
fastapi_app.include_router(go_router, tags=["Go Redirects"])
fastapi_app.include_router(file_up_router, tags=["File Uploads & Auto Build"])

# Tích hợp Endpoint Python Sandbox Execution
fastapi_app.include_router(compiler_router, prefix="/v1/python", tags=["Python Sandbox"])

app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 23091))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
