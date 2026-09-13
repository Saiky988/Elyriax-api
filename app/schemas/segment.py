from typing import List
from pydantic import BaseModel

class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str

class TranscriptionResponse(BaseModel):
    language: str
    duration: float
    text: str
    segments: List[Segment]

class TranslationRequest(BaseModel):
    segments: List[Segment]

class TranslatedSegment(BaseModel):
    id: int
    start: float
    end: float
    source: str
    text: str

class TranslationResponse(BaseModel):
    segments: List[TranslatedSegment]