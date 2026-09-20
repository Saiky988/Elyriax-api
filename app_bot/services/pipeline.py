import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from app.schemas.segment import Segment
from app.services.transcription import TranscriptionService
from app.services.translator import TranslationService
from app.utils.ffmpeg import extract_audio_from_video


def format_srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@dataclass
class PipelineMetrics:
    srt_path: Path
    temp_dir: str
    segment_count: int
    audio_duration: float
    detected_language: str


class BotSubPipeline:
    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.translation_service = TranslationService()

    async def process_file_to_srt(
        self,
        file_bytes: bytes,
        filename: str,
        translate: bool = True,
    ) -> PipelineMetrics:
        prefix = "vietsub_runtime_" if translate else "raw_srt_runtime_"
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        input_file = temp_dir / filename
        audio_file = temp_dir / "extracted_audio.mp3"
        suffix = "_vietsub" if translate else ""
        srt_file = temp_dir / f"{Path(filename).stem}{suffix}.srt"

        with open(input_file, "wb") as f:
            f.write(file_bytes)

        await extract_audio_from_video(input_file, audio_file)

        transcription_res = await self.transcription_service.transcribe(audio_file)
        if not transcription_res.segments:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ValueError("Không thể tách âm thanh hoặc nhận diện được giọng nói hợp lệ.")

        if translate:
            segments_input = [
                Segment(id=s.id, start=s.start, end=s.end, text=s.text)
                for s in transcription_res.segments
            ]
            translation_res = await self.translation_service.translate(segments_input)
            final_segments = translation_res.segments
        else:
            final_segments = transcription_res.segments

        srt_lines = []
        for idx, seg in enumerate(final_segments, start=1):
            start_str = format_srt_time(seg.start)
            end_str = format_srt_time(seg.end)
            text_clean = seg.text.strip().replace("\r\n", " ").replace("\n", " ")
            srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text_clean}\n")

        with open(srt_file, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

        return PipelineMetrics(
            srt_path=srt_file,
            temp_dir=str(temp_dir),
            segment_count=len(final_segments),
            audio_duration=getattr(transcription_res, "duration", 0.0),
            detected_language=getattr(transcription_res, "language", "Unknown"),
        )


bot_pipeline = BotSubPipeline()
