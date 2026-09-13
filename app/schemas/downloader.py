from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class DownloadRequest(BaseModel):
    url: str = Field(..., description="Link chia sẻ video Douyin hoặc text chứa link")


class MediaInfoResponse(BaseModel):
    platform: str = "douyin"
    id: str
    title: str
    author: str
    cover: Optional[str] = None
    duration: float = 0.0
    download_url: Optional[str] = None
    is_video: bool = True
