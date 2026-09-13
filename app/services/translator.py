import os
import json
import asyncio
from typing import List, Dict
from google import genai
from google.genai import types
from app.schemas.segment import Segment, TranslatedSegment, TranslationResponse

SYSTEM_INSTRUCTION = """Bạn là biên dịch viên Vietsub chuyên dịch hoạt hình Trung Quốc, Douyin animation, donghua ngắn và video kể chuyện Trung Quốc sang tiếng Việt.

Nhiệm vụ:
Dịch các subtitle segments tiếng Trung sang tiếng Việt tự nhiên, dễ đọc và đúng ngữ cảnh.

QUY TẮC:
1. Đọc toàn bộ segments trong cụm để hiểu context.
2. Không dịch máy móc từng chữ. Ưu tiên: Tự nhiên > sát từng từ nhưng tuyệt đối không làm thay đổi ý nghĩa.
3. Giữ nguyên ID. Mỗi ID trong input PHẢI xuất hiện đúng một lần trong output.
4. Không bỏ sót segment, không thêm segment, không gộp hay tách segment.
5. Một câu có thể bị chia thành nhiều segment: hãy dựa vào context xung quanh để dịch tự nhiên nhưng vẫn trả về từng ID riêng.
6. Giữ xưng hô nhất quán dựa trên context: tôi / cậu, anh / em, chị / em, tao / mày, ta / ngươi, huynh / muội, v.v. Không mặc định dùng "tôi / bạn".
7. Giữ nguyên tên nhân vật, địa danh, thuật ngữ và meme/slang Douyin theo ngữ cảnh tự nhiên.
8. Subtitle tiếng Việt ngắn gọn, súc tích, không thêm từ thừa hay chú thích bên ngoài.

OUTPUT FORMAT:
Chỉ trả về JSON hợp lệ:
{
  "segments": [
    {
      "id": 0,
      "text": "..."
    }
  ]
}
Không dùng markdown block (```json). Không thêm bất kỳ text nào ngoài JSON."""

BATCH_SIZE = 40  # Kích thước an toàn để Gemini trả về đủ 100% ID không bị cắt đuôi

class TranslationService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Biến môi trường GEMINI_API_KEY chưa được thiết lập.")
        self.client = genai.Client(api_key=api_key)

    async def _translate_batch(self, batch_segments: List[Segment]) -> Dict[int, str]:
        payload = [{"id": seg.id, "text": seg.text} for seg in batch_segments]
        prompt_content = json.dumps(payload, ensure_ascii=False)

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model="gemini-3.1-flash-lite",
                contents=prompt_content,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
        except Exception as e:
            raise RuntimeError(f"Lỗi API Gemini: {str(e)}")

        if not response or not response.text:
            raise ValueError("Gemini trả về response rỗng.")

        try:
            raw_json = json.loads(response.text.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Lỗi parse JSON: {str(e)}")

        translated_items = raw_json.get("segments")
        if not isinstance(translated_items, list):
            raise ValueError("JSON phản hồi thiếu trường 'segments'.")

        batch_input_ids = {seg.id for seg in batch_segments}
        batch_map = {}

        for item in translated_items:
            seg_id = item.get("id")
            text = item.get("text", "").strip()

            if seg_id is None or seg_id not in batch_input_ids:
                continue  # Bỏ qua ID rác nếu có
            if seg_id in batch_map:
                continue

            batch_map[seg_id] = text

        # Kiểm tra nếu cụm này bị thiếu ID
        if len(batch_map) != len(batch_input_ids):
            missing = batch_input_ids - set(batch_map.keys())
            raise ValueError(f"Gemini dịch thiếu các segment ID: {sorted(list(missing))}")

        return batch_map

    async def translate(self, segments: List[Segment]) -> TranslationResponse:
        if not segments:
            return TranslationResponse(segments=[])

        # Chia danh sách segments thành các batch nhỏ
        batches = [segments[i:i + BATCH_SIZE] for i in range(0, len(segments), BATCH_SIZE)]
        
        all_translated_map: Dict[int, str] = {}

        # Dịch tuần tự từng batch để tránh dính Rate Limit (RPM)
        for idx, batch in enumerate(batches):
            batch_result = await self._translate_batch(batch)
            all_translated_map.update(batch_result)

        # Ghép lại với timestamp và source gốc theo đúng thứ tự
        result_segments = [
            TranslatedSegment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                source=seg.text,
                text=all_translated_map.get(seg.id, "")
            )
            for seg in segments
        ]

        return TranslationResponse(segments=result_segments)
