import json
import logging
from pathlib import Path
from typing import List, Optional
import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import TypeAdapter

from app.schemas.render import (
    RenderConfig,
    RenderJobResponse,
    RenderSegment,
    RenderStatusResponse,
)
from app.services.job_manager import job_manager
from app.services.renderer import render_service

router = APIRouter()
logger = logging.getLogger("RenderRouter")

MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_LOGO_SIZE = 10 * 1024 * 1024   # 10 MB
RUNTIME_DIR = Path("runtime/jobs")


async def save_stream_file(file: UploadFile, destination: Path, max_size: int):
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(destination, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_size:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Dung lượng tệp '{file.filename}' vượt quá giới hạn cho phép."
                )
            await out.write(chunk)


@router.post("/render", status_code=status.HTTP_202_ACCEPTED, response_model=RenderJobResponse)
async def create_render_job(
    video: UploadFile = File(...),
    logo: Optional[UploadFile] = File(None),
    segments: str = Form(...),
    config: str = Form(...)
):
    # Validate extension video
    if not video.filename or not video.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Định dạng video không được hỗ trợ. Chấp nhận: mp4, mov, mkv, webm."
        )

    # Validate JSON Payload
    try:
        segments_adapter = TypeAdapter(List[RenderSegment])
        parsed_segments = segments_adapter.validate_json(segments)
        if not parsed_segments:
            raise ValueError("Danh sách segments không được để trống.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cấu trúc segments JSON không hợp lệ: {str(e)}"
        )

    try:
        parsed_config = RenderConfig.model_validate_json(config)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cấu trúc config JSON không hợp lệ: {str(e)}"
        )

    # Khởi tạo thư mục Job an toàn
    job_temp_id = "pending"
    temp_job_dir = RUNTIME_DIR / f"temp_{job_temp_id}"
    
    # Tạo Job trong JobManager
    job_id = await job_manager.create_job(temp_job_dir)
    job_dir = RUNTIME_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_ext = Path(video.filename).suffix or ".mp4"
    video_path = job_dir / f"input{video_ext}"
    await save_stream_file(video, video_path, MAX_VIDEO_SIZE)

    logo_path = None
    if logo and logo.filename:
        logo_ext = Path(logo.filename).suffix or ".png"
        logo_path = job_dir / f"logo{logo_ext}"
        await save_stream_file(logo, logo_path, MAX_LOGO_SIZE)

    # Lưu metadata
    async with aiofiles.open(job_dir / "segments.json", "w", encoding="utf-8") as f:
        await f.write(json.dumps([s.model_dump() for s in parsed_segments], ensure_ascii=False, indent=2))

    async with aiofiles.open(job_dir / "config.json", "w", encoding="utf-8") as f:
        await f.write(parsed_config.model_dump_json(indent=2))

    # Kích hoạt background task
    import asyncio
    asyncio.create_task(
        render_service.process_job(
            job_id=job_id,
            job_dir=job_dir,
            video_path=video_path,
            logo_path=logo_path,
            segments=parsed_segments,
            config=parsed_config
        )
    )

    return RenderJobResponse(job_id=job_id, status="queued")


@router.get("/render/{job_id}", response_model=RenderStatusResponse)
async def get_render_status(job_id: str):
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy job render với ID: {job_id}"
        )

    download_url = f"/render/{job_id}/download" if job.status == "completed" else None

    return RenderStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        download_url=download_url,
        error=job.error
    )


@router.get("/render/{job_id}/download")
async def download_rendered_video(job_id: str):
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job không tồn tại."
        )

    if job.status != "completed" or not job.output_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Video chưa sẵn sàng để tải xuống. Trạng thái hiện tại: {job.status}"
        )

    file_path = Path(job.output_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp video kết quả không còn tồn tại trên máy chủ."
        )

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=f"vietsub_{job_id}.mp4"
    )
