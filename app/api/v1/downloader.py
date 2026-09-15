import os
import re
import shutil
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
import httpx

from app.schemas.downloader import DownloadRequest, MediaInfoResponse
from app.services.downloader import downloader_service
from app.core.security import decode_jwt_token

router = APIRouter()

MIME_TYPES = {
    "mp4": "video/mp4",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


@router.get("/parse", response_model=MediaInfoResponse)
@router.post("/parse", response_model=MediaInfoResponse)
@router.get("/info", response_model=MediaInfoResponse)
@router.post("/info", response_model=MediaInfoResponse)
async def parse_media_endpoint(
    request_obj: Request,
    url: Optional[str] = Query(None, description="URL video can tai"),
    body: Optional[DownloadRequest] = None,
):
    """
    Endpoint phan tich video da nen tang (Douyin, TikTok, Facebook, Instagram, Twitter/X, YouTube, Pinterest...).
    Tu dong nhan dien nen tang va tra ve link tai truc tiep cua Elyriax.
    """
    target_url = url
    if not target_url and body and body.url:
        target_url = body.url

    # Neu goi POST dang raw JSON
    if not target_url and request_obj.method == "POST":
        try:
            json_data = await request_obj.json()
            if isinstance(json_data, dict):
                target_url = json_data.get("url")
        except Exception:
            pass

    if not target_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui long cung cap tham so 'url' trong query string hoac JSON body.",
        )

    try:
        data = await downloader_service.extract_info(target_url)
        return MediaInfoResponse(**data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/download")
async def one_click_download(url: str = Query(..., description="Link video can tai 1-click")):
    """
    Endpoint tai nhanh 1-Click: Tu dong phan tich va chuyen huong (307) thang toi link tai truc tiep Elyriax.
    """
    try:
        data = await downloader_service.extract_info(url)
        download_url = data.get("download_url")
        if not download_url:
            raise HTTPException(status_code=404, detail="Khong tim thay link tai cho video nay.")
        return RedirectResponse(url=download_url, status_code=307)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/direct")
@router.get("/stream")
async def proxy_media_stream(
    request: Request,
    token: Optional[str] = Query(None, description="Token JWT ky boi Elyriax chua thong tin stream"),
    url: Optional[str] = Query(None, description="Direct URL tuy chon"),
    title: Optional[str] = Query(None, description="Tieu de file tuy chon"),
    ext: Optional[str] = Query("mp4", description="Dinh dang file (mp4, mp3, jpg)"),
):
    """
    Stream proxy truc tiep qua domain Elyriax:
    - Ho tro HTTP Range Requests (206 Partial Content) cho download manager (IDM, browser pause/resume).
    - Content-Disposition attachment (/direct) hoac inline (/stream).
    - Tu dong xu ly User-Agent va Referer chong chan hotlink cua Douyin, TikTok...
    """
    target_url = None
    file_title = "video"
    file_ext = "mp4"
    upstream_headers = {}
    disposition = "attachment" if request.url.path.endswith("/direct") else "inline"

    if token:
        try:
            payload = decode_jwt_token(token)
            target_url = payload.get("url")
            file_title = payload.get("title") or file_title
            file_ext = payload.get("ext") or file_ext
            upstream_headers = payload.get("headers") or {}
            if "disposition" in payload:
                disposition = payload["disposition"]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Token stream khong hop le hoac da het han: {e}")
    elif url:
        target_url = url
        file_title = title or file_title
        file_ext = ext or file_ext
        # Auto-detect headers neu goi bang url truc tiep
        if "douyin" in target_url:
            upstream_headers = {
                "Referer": "https://www.douyin.com/",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15",
            }
        elif "tiktok" in target_url:
            upstream_headers = {
                "Referer": "https://www.tiktok.com/",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            }
        else:
            upstream_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
    else:
        raise HTTPException(status_code=400, detail="Thieu tham so 'token' hoac 'url'.")

    # Range header forwarding
    client_range = request.headers.get("range")
    if client_range:
        upstream_headers["range"] = client_range

    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    try:
        req = client.build_request("GET", target_url, headers=upstream_headers)
        upstream_resp = await client.send(req, stream=True)
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Khong the ket noi toi may chu media: {e}")

    # Response headers
    content_type = upstream_resp.headers.get("content-type") or MIME_TYPES.get(file_ext.lower(), "application/octet-stream")

    # RFC 5987 / RFC 6266 filename encoding (pure 7-bit ASCII for filename, UTF-8 percent-encoded for filename*)
    ascii_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", file_title).strip("_") or "media"
    encoded_filename = quote(f"{file_title}.{file_ext}")
    content_disposition = f'{disposition}; filename="{ascii_title}.{file_ext}"; filename*=UTF-8\'\'{encoded_filename}'

    resp_headers = {
        "Content-Disposition": content_disposition,
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, Content-Range, Accept-Ranges",
    }

    if "content-length" in upstream_resp.headers:
        resp_headers["Content-Length"] = upstream_resp.headers["content-length"]
    if "content-range" in upstream_resp.headers:
        resp_headers["Content-Range"] = upstream_resp.headers["content-range"]

    async def stream_generator():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )


@router.post("/file")
async def download_media_file(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Endpoint tai file ve may chu phuc vu pipeline Vietsub Studio.
    """
    try:
        file_path, title, temp_dir = await downloader_service.download_video(request.url)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    filename = f"{safe_title or 'video'}.mp4"

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )