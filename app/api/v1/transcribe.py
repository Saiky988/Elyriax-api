import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.schemas.segment import TranscriptionResponse
from app.services.transcription import TranscriptionService
from app.utils.ffmpeg import extract_audio_from_video

router = APIRouter()
transcription_service = TranscriptionService()

@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_video(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".flv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Định dạng tệp không hợp lệ. Vui lòng tải lên file video."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_file_path = temp_path / file.filename
        audio_file_path = temp_path / "extracted_audio.mp3"

        with open(video_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            await extract_audio_from_video(video_file_path, audio_file_path)
            result = await transcription_service.transcribe(audio_file_path)
            return result
        except Exception as err:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Xử lý thất bại: {str(err)}"
            )