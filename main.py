import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent))

import static_ffmpeg
static_ffmpeg.add_paths()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.transcribe import router as transcribe_router
from app.api.v1.translate import router as translate_router
from app.api.v1.subtitle import router as subtitle_router
from app.api.v1.render import router as render_router
from app.services.job_manager import job_manager
from app_bot.app import bot

from app.api.v1.downloader import router as downloader_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Main")


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    bot_task = None
    if bot_token:
        bot_task = asyncio.create_task(bot.start(bot_token))
    else:
        logger.warning("TOKEN not found in environment.")

    yield

    # Dọn dẹp khi tắt tiến trình
    cleanup_task.cancel()
    if bot_task:
        logger.info("Shutting down Discord Bot...")
        await bot.close()
        bot_task.cancel()


app = FastAPI(
    title="Vietsub Studio API",
    version="1.0.3",
    lifespan=lifespan
)

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(downloader_router, prefix="/api/v1/downloader", tags=["Downloader"])
app.include_router(transcribe_router, prefix="/api/v1", tags=["Transcription"])
app.include_router(translate_router, prefix="/api/v1", tags=["Translation"])
app.include_router(subtitle_router, prefix="/api/v1", tags=["Subtitles"])
app.include_router(render_router, prefix="/api/v1", tags=["Rendering"])

if __name__ == "__main__":
    port = int(os.getenv("PORT"))
    uvicorn.run(app, host="0.0.0.0", port=port)