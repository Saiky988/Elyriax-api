from typing import List, Optional
from pydantic import BaseModel


class SubtitleTextItem(BaseModel):
    id: Optional[int] = None
    start: Optional[float] = None
    end: Optional[float] = None
    text: str


class ExportTextRequest(BaseModel):
    segments: List[SubtitleTextItem]