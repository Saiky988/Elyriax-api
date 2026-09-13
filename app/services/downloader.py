import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import yt_dlp

logger = logging.getLogger("DownloaderService")


class DownloaderService:
    def __init__(self):
        self._ydl_opts_base = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                "Referer": "https://www.douyin.com/",
            },
        }

    def _clean_url(self, raw_text: str) -> str:
        match = re.search(r"https?://[^\s]+", raw_text)
        if not match:
            raise ValueError("Không tìm thấy liên kết URL hợp lệ trong nội dung gửi lên.")
        return match.group(0)

    async def extract_info(self, raw_url: str) -> Dict:
        target_url = self._clean_url(raw_url)

        def _extract():
            with yt_dlp.YoutubeDL(self._ydl_opts_base) as ydl:
                return ydl.extract_info(target_url, download=False)

        try:
            info = await asyncio.to_thread(_extract)
        except Exception as e:
            logger.error(f"Lỗi extract Douyin metadata: {str(e)}")
            raise RuntimeError(f"Không thể cào dữ liệu video từ Douyin: {str(e)}")

        video_id = info.get("id", "unknown")
        title = info.get("title", f"douyin_{video_id}")
        uploader = info.get("uploader", "Douyin Creator")
        thumbnail = info.get("thumbnail")
        duration = float(info.get("duration", 0.0))

        download_url = info.get("url")
        if not download_url and "formats" in info:
            formats = [f for f in info["formats"] if f.get("vcodec") != "none"]
            if formats:
                download_url = formats[-1].get("url")

        return {
            "platform": "douyin",
            "id": video_id,
            "title": title,
            "author": uploader,
            "cover": thumbnail,
            "duration": duration,
            "download_url": download_url,
            "is_video": True,
        }

    async def download_video(self, raw_url: str) -> Tuple[Path, str, str]:
        target_url = self._clean_url(raw_url)
        temp_dir = Path(tempfile.mkdtemp(prefix="douyin_dl_"))
        output_template = str(temp_dir / "%(id)s.%(ext)s")

        opts = {
            **self._ydl_opts_base,
            "outtmpl": output_template,
            "format": "bestvideo+bestaudio/best",
        }

        def _download():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info))
                return downloaded_file, info.get("title", info.get("id", "douyin_video"))

        try:
            downloaded_path, video_title = await asyncio.to_thread(_download)
            if not downloaded_path.exists():
                raise FileNotFoundError("Tệp sau khi tải không tồn tại trên máy chủ.")
            return downloaded_path, video_title, str(temp_dir)
        except Exception as e:
            logger.error(f"Lỗi khi download Douyin: {str(e)}")
            raise RuntimeError(f"Tải video Douyin thất bại: {str(e)}")


downloader_service = DownloaderService()