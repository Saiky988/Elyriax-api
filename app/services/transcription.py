import os
from pathlib import Path
from groq import Groq
from app.schemas.segment import Segment, TranscriptionResponse

class TranscriptionService:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

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