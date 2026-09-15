import asyncio
import base64
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx
import yt_dlp

from app.core.config import settings
from app.core.security import create_jwt_token, decode_jwt_token

logger = logging.getLogger("DownloaderService")

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


class DownloaderService:
    def __init__(self):
        self._ydl_opts_base = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "http_headers": {
                "User-Agent": IOS_UA,
                "Referer": "https://www.douyin.com/",
            },
        }

    def clean_url(self, raw_text: str) -> str:
        """Trich xuat URL sach tu van ban chua URL (ho tro link chia se Douyin, TikTok...)."""
        if not raw_text:
            raise ValueError("Vui long cung cap duong dan video hop le.")
        match = re.search(r"https?://[^\s\"'<>]+", raw_text)
        if not match:
            raise ValueError("Khong tim thay lien ket URL hop le trong noi dung gui len.")
        url = match.group(0).strip()
        # Loai bo cac dau cau o cuoi URL neu co
        url = re.sub(r"[.,;!?)>}\u3002\uff0c\uff01\uff1f\uff09]+$", "", url)
        return url

    def detect_platform(self, url: str) -> str:
        """Tu dong nhan dien nen tang video tu URL."""
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()

        if any(h in host for h in ["douyin.com", "iesdouyin.com"]):
            return "douyin"
        if any(h in host for h in ["tiktok.com"]):
            return "tiktok"
        if any(h in host for h in ["facebook.com", "fb.watch", "fb.com", "fb.me"]):
            return "facebook"
        if any(h in host for h in ["instagram.com", "instagr.am"]):
            return "instagram"
        if any(h in host for h in ["twitter.com", "x.com", "t.co"]):
            return "twitter"
        if any(h in host for h in ["youtube.com", "youtu.be"]):
            return "youtube"
        if any(h in host for h in ["pinterest.com", "pin.it"]):
            return "pinterest"
        if any(h in host for h in ["threads.net"]):
            return "threads"
        if any(h in host for h in ["kuaishou.com", "gifshow.com"]):
            return "kuaishou"
        if any(h in host for h in ["bilibili.com", "b23.tv"]):
            return "bilibili"
        return "general"

    def generate_direct_link(
        self,
        upstream_url: str,
        title: str,
        ext: str = "mp4",
        headers: Optional[Dict[str, str]] = None,
        disposition: str = "attachment",
    ) -> str:
        """Tao link tai truc tiep cua Elyriax thay vi tra ve link goc tu upstream."""
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "video"
        payload = {
            "url": upstream_url,
            "title": safe_title,
            "ext": ext,
            "headers": headers or {},
            "disposition": disposition,
        }
        token = create_jwt_token(payload, expires_days=30)
        route = "direct" if disposition == "attachment" else "stream"
        return f"{settings.BASE_URL}/v1/downloader/{route}?token={token}"

    async def _parse_douyinsaver(self, url: str) -> Optional[Dict[str, Any]]:
        """Goi API DouyinSaver de phan tich video / anh Douyin."""
        api_endpoint = "https://api.douyinsaver.com/api/parse"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    api_endpoint,
                    json={"url": url},
                    headers={"Content-Type": "application/json", "User-Agent": DEFAULT_UA},
                )
                if resp.status_code != 200:
                    logger.warning(f"DouyinSaver API returned status {resp.status_code}")
                    return None

                data = resp.json()
                if not data or not data.get("title") and not data.get("qualities"):
                    return None

                title = data.get("title", "douyin_video").strip()
                author = data.get("author", "Douyin Creator")
                cover = data.get("cover")
                duration_raw = data.get("duration", 0)
                duration = round(duration_raw / 1000.0, 2) if duration_raw > 1000 else float(duration_raw)
                aweme_id = data.get("aweme_id", "douyin")

                req_headers = {"Referer": "https://www.douyin.com/", "User-Agent": IOS_UA}
                medias = []
                qualities = data.get("qualities", [])

                best_direct_url = None
                best_stream_url = None
                best_cdn_url = None

                for q in qualities:
                    raw_q_url = q.get("url")
                    if not raw_q_url:
                        continue
                    label = q.get("label", "HD")
                    direct_dl = self.generate_direct_link(raw_q_url, title, "mp4", headers=req_headers, disposition="attachment")
                    inline_stream = self.generate_direct_link(raw_q_url, title, "mp4", headers=req_headers, disposition="inline")

                    if not best_direct_url:
                        best_direct_url = direct_dl
                        best_stream_url = inline_stream
                        best_cdn_url = raw_q_url

                    medias.append({
                        "type": "video",
                        "label": label,
                        "quality": label,
                        "width": q.get("width"),
                        "height": q.get("height"),
                        "bitrate": q.get("bitrate"),
                        "download_url": direct_dl,
                        "stream_url": inline_stream,
                        "cdn_url": raw_q_url,
                    })

                # Proxy cover image if available
                direct_cover = self.generate_direct_link(cover, f"{title}_cover", "jpg", headers=req_headers) if cover else None

                # Audio URL if present
                audio_url = None
                if data.get("audio_url"):
                    audio_url = self.generate_direct_link(data["audio_url"], f"{title}_audio", "mp3", headers=req_headers)

                # Images list if album
                images = []
                for idx, img_url in enumerate(data.get("images", []), 1):
                    images.append(self.generate_direct_link(img_url, f"{title}_image_{idx}", "jpg", headers=req_headers))

                is_video = (data.get("media_type") == "video") or bool(medias)

                return {
                    "status": "success",
                    "platform": "douyin",
                    "id": str(aweme_id),
                    "title": title,
                    "author": author,
                    "cover": direct_cover or cover,
                    "duration": duration,
                    "download_url": best_direct_url or (images[0] if images else None),
                    "stream_url": best_stream_url,
                    "cdn_url": best_cdn_url,
                    "is_video": is_video,
                    "medias": medias,
                    "audio_url": audio_url,
                    "images": images,
                    "original_url": url,
                }
        except Exception as e:
            logger.warning(f"Error calling DouyinSaver: {e}")
            return None

    async def _parse_phimtat(self, url: str) -> Optional[Dict[str, Any]]:
        """Goi Gateway Phimtat / SnapVideo de phan tich video da nen tang (TikTok, Twitter, FB, Insta...)."""
        try:
            req_headers = {"User-Agent": IOS_UA, "Accept": "application/json"}

            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                async def _fetch_snap(target_u: str):
                    b64 = base64.b64encode(target_u.encode("utf-8")).decode("utf-8")
                    gw = f"https://api.phimtat.vn/snapvideo/red64.php?url={b64}"
                    for attempt in range(2):
                        r = await client.get(gw, headers=req_headers)
                        if r.status_code == 200:
                            try:
                                return r.json()
                            except Exception:
                                return None
                        elif r.status_code == 429:
                            await asyncio.sleep(1.2)
                            continue
                    return None

                current_target = url
                data = None

                # Tu dong dong y dieu khoan va reload lay link video CDN thuc te (toi da 5 vong lap)
                for _ in range(5):
                    b64_url = base64.b64encode(current_target.encode("utf-8")).decode("utf-8")
                    api_url = (
                        f"https://api.phimtat.vn/json/snapvideo.json?"
                        f"api-key=JILx9BLUzuCnwpXaSAygF9X10hIW3rNN"
                        f"&lang=vi&ver=7&ask_format=false&show_menu=false&skip_update=true&b64={b64_url}"
                    )
                    data = await _fetch_snap(api_url)
                    if not data or not isinstance(data, dict):
                        break

                    # Xu ly Pop-up dieu khoan neu xuat hien
                    medias = data.get("medias", {})
                    agree_url = None
                    if isinstance(medias, dict):
                        agree_url = medias.get("✅ Đồng ý") or medias.get("agree")
                    if not agree_url:
                        agree_url = data.get("✅ Đồng ý") or data.get("agree")

                    if agree_url:
                        agree_res = await _fetch_snap(agree_url)
                        if agree_res and isinstance(agree_res, dict) and "reload" in agree_res:
                            current_target = agree_res["reload"]
                            await asyncio.sleep(0.5)
                            continue
                        elif agree_res and isinstance(agree_res, dict) and isinstance(agree_res.get("medias"), dict) and "✅ Đồng ý" not in agree_res["medias"]:
                            data = agree_res
                            break
                    break

                if not data or not isinstance(data, dict):
                    return None

                raw_medias = data.get("medias", {})
                if not isinstance(raw_medias, dict) or not raw_medias or "✅ Đồng ý" in raw_medias or data.get("source") == "notice":
                    return None

                title = data.get("title", "video").strip()
                source = data.get("source", "video")
                thumbnail = data.get("thumbnail")

                media_items = []
                best_direct_url = None
                best_stream_url = None
                best_cdn_url = None
                audio_url = None

                for label, raw_media_url in raw_medias.items():
                    if not raw_media_url or not isinstance(raw_media_url, str) or raw_media_url.startswith("{{"):
                        continue

                    # Lam sach label (loai bo cac icon emoji khoi label)
                    clean_label = re.sub(r"[^\w\s-]", "", label).strip() or label
                    is_audio = any(k in label.lower() for k in ["mp3", "audio", "âm thanh"])
                    is_img = any(k in label.lower() for k in ["image", "ảnh", "photo"])

                    ext = "mp3" if is_audio else ("jpg" if is_img else "mp4")
                    media_type = "audio" if is_audio else ("image" if is_img else "video")

                    direct_dl = self.generate_direct_link(raw_media_url, title, ext, disposition="attachment")
                    inline_stream = self.generate_direct_link(raw_media_url, title, ext, disposition="inline")

                    if is_audio and not audio_url:
                        audio_url = direct_dl
                    elif not is_audio and not best_direct_url:
                        best_direct_url = direct_dl
                        best_stream_url = inline_stream
                        best_cdn_url = raw_media_url

                    media_items.append({
                        "type": media_type,
                        "label": clean_label,
                        "quality": clean_label,
                        "width": None,
                        "height": None,
                        "bitrate": None,
                        "download_url": direct_dl,
                        "stream_url": inline_stream,
                        "cdn_url": raw_media_url,
                    })

                if not media_items:
                    return None

                direct_cover = self.generate_direct_link(thumbnail, f"{title}_cover", "jpg") if thumbnail else None

                return {
                    "status": "success",
                    "platform": source,
                    "id": str(abs(hash(url)) % 100000000),
                    "title": title,
                    "author": data.get("author", "Creator"),
                    "cover": direct_cover or thumbnail,
                    "duration": float(data.get("duration", 0.0)),
                    "download_url": best_direct_url or media_items[0]["download_url"],
                    "stream_url": best_stream_url,
                    "cdn_url": best_cdn_url or raw_medias.get(list(raw_medias.keys())[0]),
                    "is_video": any(m["type"] == "video" for m in media_items),
                    "medias": media_items,
                    "audio_url": audio_url,
                    "images": [],
                    "original_url": url,
                }
        except Exception as e:
            logger.warning(f"Error calling Phimtat gateway: {e}")
            return None

    async def _parse_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        """Fallback su dung yt-dlp khi cac API ben ngoai khong tra ve ket qua."""
        def _extract():
            with yt_dlp.YoutubeDL(self._ydl_opts_base) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = await asyncio.to_thread(_extract)
            video_id = info.get("id", "video")
            title = info.get("title", f"video_{video_id}").strip()
            uploader = info.get("uploader", "Creator")
            thumbnail = info.get("thumbnail")
            duration = float(info.get("duration", 0.0) or 0.0)

            download_url = info.get("url")
            raw_cdn_url = download_url
            medias = []

            if "formats" in info:
                video_formats = [f for f in info["formats"] if f.get("vcodec") != "none" and f.get("url")]
                for fmt in video_formats[-5:]:  # Lay 5 format tot nhat
                    f_url = fmt.get("url")
                    if not f_url:
                        continue
                    q_label = fmt.get("format_note") or f"{fmt.get('height', 'HD')}p"
                    direct_dl = self.generate_direct_link(f_url, title, "mp4", disposition="attachment")
                    inline_stream = self.generate_direct_link(f_url, title, "mp4", disposition="inline")
                    if not raw_cdn_url:
                        raw_cdn_url = f_url
                    medias.append({
                        "type": "video",
                        "label": q_label,
                        "quality": q_label,
                        "width": fmt.get("width"),
                        "height": fmt.get("height"),
                        "bitrate": fmt.get("tbr"),
                        "download_url": direct_dl,
                        "stream_url": inline_stream,
                        "cdn_url": f_url,
                    })

            if not download_url and medias:
                download_url = medias[-1]["download_url"]
            elif download_url:
                download_url = self.generate_direct_link(download_url, title, "mp4", disposition="attachment")

            direct_cover = self.generate_direct_link(thumbnail, f"{title}_cover", "jpg") if thumbnail else None

            return {
                "status": "success",
                "platform": info.get("extractor_key", "general").lower(),
                "id": str(video_id),
                "title": title,
                "author": uploader,
                "cover": direct_cover or thumbnail,
                "duration": duration,
                "download_url": download_url,
                "stream_url": medias[-1]["stream_url"] if medias else None,
                "cdn_url": raw_cdn_url,
                "is_video": True,
                "medias": medias,
                "audio_url": None,
                "images": [],
                "original_url": url,
            }
        except Exception as e:
            logger.warning(f"Error extracting with yt-dlp: {e}")
            return None

    async def extract_info(self, raw_url: str) -> Dict[str, Any]:
        """Phan tich va trich xuat link tai truc tiep Elyriax voi co che Auto-Detect & Fallback."""
        target_url = self.clean_url(raw_url)
        platform = self.detect_platform(target_url)
        logger.info(f"Detected platform '{platform}' for URL: {target_url}")

        result = None

        # 1. Neu la Douyin: Uu tien DouyinSaver -> Phimtat -> yt-dlp
        if platform == "douyin":
            result = await self._parse_douyinsaver(target_url)
            if not result:
                result = await self._parse_phimtat(target_url)
            if not result:
                result = await self._parse_ytdlp(target_url)

        # 2. Neu la TikTok: Uu tien Phimtat -> DouyinSaver -> yt-dlp
        elif platform == "tiktok":
            result = await self._parse_phimtat(target_url)
            if not result:
                result = await self._parse_douyinsaver(target_url)
            if not result:
                result = await self._parse_ytdlp(target_url)

        # 3. Cac nen tang khac (Facebook, Instagram, Twitter/X, YouTube, Pinterest, v.v.)
        else:
            result = await self._parse_phimtat(target_url)
            if not result:
                result = await self._parse_ytdlp(target_url)

        if not result:
            raise RuntimeError("Khong the phan tich hoac lay link tai cho video nay tu cac may chu.")

        return result

    async def download_video(self, raw_url: str) -> Tuple[Path, str, str]:
        """Tai file video truc tiep ve o dia tam phuc vu pipeline Vietsub Studio."""
        target_url = self.clean_url(raw_url)
        temp_dir = Path(tempfile.mkdtemp(prefix="elyriax_dl_"))
        output_template = str(temp_dir / "%(id)s.%(ext)s")

        # Thu lay link qua extract_info truoc
        try:
            info = await self.extract_info(target_url)
            raw_target_url = None
            if info.get("medias"):
                # Giai ma lay upstream url
                first_dl = info["medias"][0]["download_url"]
                match = re.search(r"token=([^&]+)", first_dl)
                if match:
                    decoded = decode_jwt_token(match.group(1))
                    raw_target_url = decoded.get("url")

            if raw_target_url:
                target_url = raw_target_url
        except Exception:
            pass

        opts = {
            **self._ydl_opts_base,
            "outtmpl": output_template,
            "format": "bestvideo+bestaudio/best",
        }

        def _download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info))
                return downloaded_file, info.get("title", info.get("id", "video"))

        try:
            downloaded_path, video_title = await asyncio.to_thread(_download)
            if not downloaded_path.exists():
                raise FileNotFoundError("Tep sau khi tai khong ton tai tren may chu.")
            return downloaded_path, video_title, str(temp_dir)
        except Exception as e:
            logger.error(f"Loi khi download video: {str(e)}")
            raise RuntimeError(f"Tai video that bai: {str(e)}")


downloader_service = DownloaderService()