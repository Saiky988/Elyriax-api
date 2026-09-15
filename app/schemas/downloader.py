from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    url: str = Field(..., description="Link chia se video hoac text chua link (Douyin, TikTok, Facebook, Instagram, Twitter/X, YouTube, Pinterest...)")


class MediaQualityItem(BaseModel):
    type: str = "video"
    label: str
    quality: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bitrate: Optional[int] = None
    download_url: str
    stream_url: Optional[str] = None


class MediaInfoResponse(BaseModel):
    status: str = "success"
    platform: str = "douyin"
    id: str
    title: str
    author: str
    cover: Optional[str] = None
    duration: float = 0.0
    download_url: Optional[str] = None
    stream_url: Optional[str] = None
    is_video: bool = True
    medias: Optional[List[MediaQualityItem]] = []
    audio_url: Optional[str] = None
    images: Optional[List[str]] = []
    original_url: Optional[str] = None
