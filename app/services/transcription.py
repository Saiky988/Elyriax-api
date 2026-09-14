import os
from pathlib import Path
from groq import Groq
from app.schemas.segment import Segment, TranscriptionResponse

class TranscriptionService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ValueError("GROQ_API_KEY is not set.")
            self._client = Groq(api_key=api_key)
        return self._client

    async def transcribe(self, audio_path: Path) -> TranscriptionResponse:
        with open(audio_path, "rb") as file:
            transcription = self.client.audio.transcriptions.create(
                file=(audio_path.name, file.read()),
                model="whisper-large-v3",
                temperature=0,
                response_format="verbose_json",
            )
        
        raw_data = transcription.model_dump() if hasattr(transcription, "model_dump") else transcription

        segments = [
            Segment(
                id=seg.get("id", idx),
                start=round(seg.get("start", 0.0), 2),
                end=round(seg.get("end", 0.0), 2),
                text=seg.get("text", "").strip()
            )
            for idx, seg in enumerate(raw_data.get("segments", []))
        ]

        return TranscriptionResponse(
            language=raw_data.get("language", ""),
            duration=round(raw_data.get("duration", 0.0), 2),
            text=raw_data.get("text", "").strip(),
            segments=segments
        )