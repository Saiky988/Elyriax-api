from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class RenderSegment(BaseModel):
    id: int
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    source: Optional[str] = ""
    text: str


class SubtitlePosition(BaseModel):
    x: float = Field(default=50.0, ge=0.0, le=100.0)
    y: float = Field(default=88.0, ge=0.0, le=100.0)


class SubtitleConfig(BaseModel):
    font: str = Field(default="Inter")
    fontSize: int = Field(default=15, gt=0)
    position: SubtitlePosition = Field(default_factory=SubtitlePosition)
    outline: float = Field(default=1.5, ge=0.0)
    shadow: float = Field(default=1.0, ge=0.0)
    weight: int = Field(default=700, ge=100, le=900)
    color: str = Field(default="#ffffff")
    fadeInOut: bool = Field(default=True)
    maxCharsPerLine: int = Field(default=28, ge=15, le=50)
    maxLines: int = Field(default=2, ge=1, le=3)
    autoSplitLong: bool = Field(default=True)


class BlurConfig(BaseModel):
    enabled: bool = Field(default=True)
    x: float = Field(default=15.0, ge=0.0, le=100.0)
    y: float = Field(default=83.0, ge=0.0, le=100.0)
    width: float = Field(default=70.0, ge=0.0, le=100.0)
    height: float = Field(default=11.0, ge=0.0, le=100.0)
    strength: float = Field(default=3.5, ge=0.0)
    borderRadius: int = Field(default=18, ge=0)
    liquidGlass: bool = Field(default=True)
    lightDiffusion: float = Field(default=0.03, ge=0.0, le=0.2)  # Tán xạ sáng xóa vết sub


class LogoConfig(BaseModel):
    enabled: bool = Field(default=False)
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-right"
    size: float = Field(default=8.0, gt=0.0, le=100.0)
    opacity: float = Field(default=100.0, ge=0.0, le=100.0)
    margin: int = Field(default=20, ge=0)


class RenderConfig(BaseModel):
    subtitle: SubtitleConfig = Field(default_factory=SubtitleConfig)
    blur: BlurConfig = Field(default_factory=BlurConfig)
    logo: LogoConfig = Field(default_factory=LogoConfig)


class RenderJobResponse(BaseModel):
    job_id: str
    status: str


class RenderStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int = Field(..., ge=0, le=100)
    message: str
    download_url: Optional[str] = None
    error: Optional[str] = None
