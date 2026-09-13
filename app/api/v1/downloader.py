import os
import shutil
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from app.schemas.downloader import DownloadRequest, MediaInfoResponse
from app.services.downloader import downloader_service

router = APIRouter()


@router.post("/info", response_model=MediaInfoResponse)
async def get_media_info(request: DownloadRequest):
    try:
        data = await downloader_service.extract_info(request.url)
        return MediaInfoResponse(**data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.post("/file")
async def download_media_file(request: DownloadRequest, background_tasks: BackgroundTasks):
    try:
        file_path, title, temp_dir = await downloader_service.download_video(request.url)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    filename = f"{safe_title or 'douyin_video'}.mp4"

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )