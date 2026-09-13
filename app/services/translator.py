import os
import json
import asyncio
import logging
from typing import List, Dict

from google import genai
from google.genai import types

from app.schemas.segment import Segment, TranslatedSegment, TranslationResponse

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """Bạn là nhà phiên dịch Vietsub đỉnh cao, chuyên phụ trách donghua, Douyin animation, short story video Trung Quốc — kiểu sub dành riêng cho Gen Z Việt coi mỗi ngày.

TRÌNH ĐỘ:
- Bạn "lướt" cả Douyin lẫn YouTube Vietsub, thấu hiểu cách Gen Z Việt nói chuyện: slang, meme, trend, cách viết tắt, câu cú ngắn gọn có nhịp.
- Bạn hiểu văn hóa Trung (修真, 古风, 都市爽文, 打脸, 系统文...) VÀ cách Việt hóa tự nhiên, không cưỡng ép.

QUY TẮC BẮT BUỘC:
1. Đọc toàn bộ segments trong batch trước khi dịch — bắt đúng context, plot twist, người nói với người nghe.
2. Tự nhiên là trên hết. Đúng kiểu sub trên TikTok/YouTube Việt Nam: ngắn, có vibe, dễ đọc, KHÔNG được dịch máy hay từng chữ một. Nhưng tuyệt đối không làm sai lệch ý nghĩa gốc, không bịa thêm nội dung, không lược mất ý.
3. Tone phù hợp: hài/huyền huyễn/drama/thảm ảnh → dùng slang Gen Z có chọn lọc (vd: "sốc vl", "ăn hành", "phốt", "flex", "cringe", "banger"...) — chỉ dùng khi ngữ cảnh hợp, không nhồi nhét. Cảnh cổ trang/nghiêm túc thì giữ văn phong trang trọng phù hợp bối cảnh.
4. Giữ nguyên ID. Mỗi ID trong input xuất hiện ĐÚNG 1 lần trong output. Không bỏ, không thêm, không gộp, không tách segment.
5. Một câu bị cắt thành nhiều segment: dựa context xung quanh để dịch mạch lạc, vẫn trả về từng ID riêng lẻ.
6. Xưng hô NHẤT QUÁN theo mạch phim và quan hệ nhân vật: ta/ngươi, huynh/muội, sư huynh/sư đệ, anh/em, chị/em, tao/mày, tôi/cậu... Không tự ý đổi giữa chừng. Không mặc định "tôi/bạn".
7. Giữ nguyên tên nhân vật, địa danh, tông môn, cảnh giới tu luyện (viết theo cách thông dụng trong cộng đồng Vietsub donghua). Slang/meme Douyin chuyển tải sang tương đương Gen Z Việt.
8. Sub ngắn gọn vừa phải, không chêm chú thích, không dấu ngoặc giải thích, không emoji trong sub trừ khi bản gốc có.

OUTPUT FORMAT:
Chỉ trả về JSON hợp lệ, đúng cấu trúc:
{
  "segments": [
    {"id": 0, "text": "..."}
  ]
}
Không markdown block. Không một ký tự nào ngoài JSON."""

BATCH_SIZE = 40
MAX_RETRIES = 3
RETRY_DELAY = 2.0

MODEL = "gemini-3.5-flash-lite"

class TranslationService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Biến môi trường GEMINI_API_KEY chưa được thiết lập.")
        self.client = genai.Client(api_key=api_key)

    # ── Core: dịch 1 batch, có retry ──────────────────────────
    async def _translate_batch(self, batch_segments: List[Segment]) -> Dict[int, str]:
        payload = [{"id": seg.id, "text": seg.text} for seg in batch_segments]
        prompt_content = json.dumps(payload, ensure_ascii=False)
        batch_input_ids = {seg.id for seg in batch_segments}

        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                batch_map = await self._call_gemini(prompt_content, batch_input_ids)
                missing = batch_input_ids - set(batch_map.keys())
                if missing:
                    raise ValueError(f"Gemini dịch thiếu các segment ID: {sorted(missing)}")
                return batch_map
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Batch %s] Lần thử %d/%d thất bại: %s",
                    batch_segments[0].id, attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * attempt)

        raise RuntimeError(
            f"Dịch batch thất bại sau {MAX_RETRIES} lần thử: {last_error}"
        )

    # ── Gọi API Gemini + validate output ──────────────────────
    async def _call_gemini(
        self, prompt_content: str, batch_input_ids: set[int]
    ) -> Dict[int, str]:
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=MODEL,
                contents=prompt_content,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
        except Exception as e:
            raise RuntimeError(f"Lỗi API Gemini: {e}") from e

        if not response or not response.text:
            raise ValueError("Gemini trả về response rỗng.")

        try:
            raw_json = json.loads(response.text.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Lỗi parse JSON: {e}") from e

        translated_items = raw_json.get("segments")
        if not isinstance(translated_items, list):
            raise ValueError("JSON phản hồi thiếu trường 'segments'.")

        batch_map: Dict[int, str] = {}
        for item in translated_items:
            seg_id = item.get("id")
            text = (item.get("text") or "").strip()

            if seg_id not in batch_input_ids or seg_id in batch_map:
                continue  # Bỏ ID rác / ID trùng lặp
            batch_map[seg_id] = text

        return batch_map

    # ── Entry point: dịch toàn bộ segments ────────────────────
    async def translate(self, segments: List[Segment]) -> TranslationResponse:
        if not segments:
            return TranslationResponse(segments=[])

        batches = [
            segments[i : i + BATCH_SIZE]
            for i in range(0, len(segments), BATCH_SIZE)
        ]

        all_translated_map: Dict[int, str] = {}
        for batch in batches:
            all_translated_map.update(await self._translate_batch(batch))

        # Khớp lại với timestamp + source gốc theo đúng thứ tự
        result_segments = [
            TranslatedSegment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                source=seg.text,
                text=all_translated_map.get(seg.id, ""),
            )
            for seg in segments
        ]

        return TranslationResponse(segments=result_segments)
