from fastapi import APIRouter, HTTPException, status
from app.schemas.segment import TranslationRequest, TranslationResponse
from app.services.translator import TranslationService

router = APIRouter()

try:
    translation_service = TranslationService()
except Exception as e:
    translation_service = None

@router.post("/translate", response_model=TranslationResponse)
async def translate_segments(request: TranslationRequest):
    if translation_service is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dịch vụ dịch thuật chưa được khởi tạo. Kiểm tra lại GEMINI_API_KEY."
        )

    try:
        result = await translation_service.translate(request.segments)
        return result
    except (ValueError, RuntimeError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dịch thất bại: {str(err)}"
        )