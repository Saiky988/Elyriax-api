from fastapi import APIRouter, HTTPException, Response, status
from app.schemas.subtitle import ExportTextRequest

router = APIRouter()


@router.post("/export-txt")
async def export_subtitles_to_txt(request: ExportTextRequest):
    if not request.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Danh sách segments không được để trống."
        )

    # Lấy text từng segment, loại bỏ dòng trống và ký tự thừa
    lines = []
    for seg in request.segments:
        clean_text = seg.text.strip().replace("\r\n", " ").replace("\n", " ")
        if clean_text:
            lines.append(clean_text)

    # Ghép thành file txt mỗi câu một dòng
    content = "\n".join(lines)

    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=voice_script.txt",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
