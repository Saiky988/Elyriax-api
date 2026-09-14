import logging
import urllib.parse
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import httpx
from bs4 import BeautifulSoup

router = APIRouter()
logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# 1. GET /v1/truyen/image/{filename:path}
# -------------------------------------------------------------
@router.get("/image/{filename:path}")
async def get_truyen_image(filename: str, request: Request):
    # Query parameters if any are appended
    query_str = request.url.query
    filename_with_query = f"{filename}?{query_str}" if query_str else filename

    base_url = "https://i.truyenvua.com/ebook/190x247/"
    image_url = f"{base_url}{filename_with_query}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                image_url,
                headers={
                    "Referer": "https://truyenggvn.com/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                }
            )

        if response.status_code != 200:
            return PlainTextResponse("Image not found or blocked", status_code=404)

        content_type = response.headers.get("content-type", "image/jpeg")
        return Response(
            content=response.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000"}
        )
    except Exception as error:
        logger.error(f"[Proxy Image Error]: {error}")
        return PlainTextResponse("Image not found or blocked", status_code=404)

# -------------------------------------------------------------
# 2. GET /v1/truyen/home
# -------------------------------------------------------------
def build_proxy_url(original_url: Optional[str]) -> str:
    if not original_url:
        return ""
    try:
        parsed = urllib.parse.urlparse(original_url)
        filename_and_query = parsed.path.split('/')[-1]
        if parsed.query:
            filename_and_query += f"?{parsed.query}"
        return f"/api/v1/truyen/image/{urllib.parse.quote(filename_and_query)}"
    except Exception:
        return original_url

@router.get("/home")
async def get_truyen_home():
    target_url = "https://m.truyenggvn.com"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                target_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": target_url
                }
            )

        soup = BeautifulSoup(response.text, "html.parser")

        trending_items = []
        for el in soup.select(".items-slide article .item"):
            caption_a = el.select_one(".slide-caption h3 a")
            title = caption_a.get_text(strip=True) if caption_a else ""
            url = caption_a.get("href", "") if caption_a else ""

            amp_img = el.select_one("amp-img")
            original_thumb = amp_img.get("src", "") if amp_img else ""

            chapter_a = el.select_one(".slide-caption > a")
            chapter_name = chapter_a.get_text(strip=True) if chapter_a else ""
            chapter_url = chapter_a.get("href", "") if chapter_a else ""

            slug = url.split('/')[-1] if url else ""

            if title:
                trending_items.append({
                    "name": title,
                    "slug": slug,
                    "url": url,
                    "thumb_url": build_proxy_url(original_thumb),
                    "original_thumb_url": original_thumb,
                    "latest_chapter": {
                        "name": chapter_name,
                        "url": chapter_url
                    }
                })

        new_items = []
        for el in soup.select(".items article.item"):
            h3_a = el.select_one("figcaption h3 a")
            title = h3_a.get_text(strip=True) if h3_a else ""
            url = h3_a.get("href", "") if h3_a else ""

            amp_img = el.select_one(".image amp-img")
            original_thumb = amp_img.get("src", "") if amp_img else ""

            time_ago_el = el.select_one(".top-notice .time-ago")
            time_ago = time_ago_el.get_text(strip=True) if time_ago_el else ""

            type_label_el = el.select_one(".top-notice .type-label")
            type_label = type_label_el.get_text(strip=True) if type_label_el else None

            chapter_a = el.select_one("figcaption .chapter a")
            chapter_name = chapter_a.get_text(strip=True) if chapter_a else ""
            chapter_url = chapter_a.get("href", "") if chapter_a else ""

            slug = url.split('/')[-1] if url else ""

            if title:
                new_items.append({
                    "name": title,
                    "slug": slug,
                    "url": url,
                    "thumb_url": build_proxy_url(original_thumb),
                    "original_thumb_url": original_thumb,
                    "time_ago": time_ago,
                    "label": type_label,
                    "latest_chapter": {
                        "name": chapter_name,
                        "url": chapter_url
                    }
                })

        return {
            "status": "success",
            "message": "Lấy dữ liệu thành công",
            "data": {
                "seoOnPage": {
                    "titleHead": "Truyện mới cập nhật",
                    "descriptionHead": "Đọc truyện tranh online chất lượng cao"
                },
                "trending_items": trending_items,
                "new_items": new_items,
            }
        }
    except Exception as error:
        logger.error(f"[Truyen Route] Fetch API Error: {error}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Không thể fetch dữ liệu từ nguồn",
                "details": str(error)
            }
        )
