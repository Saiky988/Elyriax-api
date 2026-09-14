import os
import json
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

API_KEYS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "groq_api.json"

current_key_index = 0

def get_next_api_key() -> Optional[str]:
    global current_key_index
    keys = []
    if API_KEYS_PATH.exists():
        try:
            with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                keys = data.get("keys", [])
        except Exception as e:
            logger.warning(f"Failed to read groq_api.json: {e}")

    if not keys and settings.GROQ_API_KEY:
        # Check if comma-separated
        keys = [k.strip() for k in settings.GROQ_API_KEY.split(",") if k.strip()]

    if not keys:
        return None

    key = keys[current_key_index % len(keys)]
    current_key_index = (current_key_index + 1) % len(keys)
    return key

SUPPORTED_LANGUAGES = {
    "auto": "Auto Detect",
    "vi": "Vietnamese",
    "en": "English",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
    "th": "Thai",
    "id": "Indonesian",
    "lo": "Lao",
    "km": "Khmer",
    "my": "Burmese",
    "ms": "Malay",
    "ph": "Filipino",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "hi": "Hindi",
    "ar": "Arabic",
    "tr": "Turkish",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "cs": "Czech",
    "el": "Greek",
    "he": "Hebrew",
    "ro": "Romanian",
    "hu": "Hungarian",
    "uk": "Ukrainian"
}

SYSTEM_PROMPT_STEP1 = """
You are a "Cross-Cultural Chat Normalizer". 
Your job: Decode internet slang, teencode, and abbreviations into a clear "Global Meaning".

Priority:
1. Preserve intent (Sarcasm, question, statement)
2. Preserve tone (Aggressive, friendly, neutral)
3. Preserve social meaning (What the speaker MEANS, not just says)

Rules:
- Expand teencode (k->không, j->gì, r->rồi, bik->biết,...)
- Resolve Vietnamese slang (lỏ, phèn, báo,...)
- Infer omitted subjects (I, you, they)
- Output ONLY JSON.

Example:
Input: "bik vậy vui lắm ko?"
Output: {"normalized": "Biết vậy vui lắm không?", "intent": "rhetorical sarcasm", "meaning": "Do you think that is actually funny? (Implying it's not)"}
"""

def build_system_prompt_step2(target_langs: List[str]) -> str:
    lang_names = ", ".join([SUPPORTED_LANGUAGES.get(l, l) for l in target_langs])
    return f"""
You are a "Meaning-to-Multilingual Engine".
Input is a "Global Meaning" and "Intent".
Translate this meaning into these languages: {lang_names}.

Rules:
- DO NOT translate the raw text. Translate the INTENT.
- Use natural, native-level phrasing for each language.
- Output ONLY JSON with language codes as keys.

Example Input: {{"meaning": "Who asked?"}}
Example Output: {{"en": "Who asked?", "vi": "Có ai hỏi đâu?", "ja": "誰も聞いてないよ"}}
"""

class TranslateRequest(BaseModel):
    text: Optional[str] = None
    targets: Optional[List[str]] = ["en", "vi", "ja", "ko", "es"]

@router.post("")
@router.post("/")
async def translate_text(req: TranslateRequest):
    if not req.text:
        return JSONResponse(status_code=400, content={"success": False, "message": "Missing text"})

    api_key = get_next_api_key()
    if not api_key:
        return JSONResponse(status_code=500, content={"success": False, "message": "No API Key"})

    targets = req.targets or ["en", "vi", "ja", "ko", "es"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1
            step1_resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={
                    "model": "openai/gpt-oss-20b",
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT_STEP1},
                        {"role": "user", "content": req.text}
                    ]
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )

            if step1_resp.status_code != 200:
                raise Exception(f"Step 1 failed with code {step1_resp.status_code}: {step1_resp.text}")

            analysis = json.loads(step1_resp.json()["choices"][0]["message"]["content"])

            # Step 2
            step2_resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={
                    "model": "openai/gpt-oss-20b",
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": build_system_prompt_step2(targets)},
                        {"role": "user", "content": json.dumps({"meaning": analysis.get("meaning"), "intent": analysis.get("intent")})}
                    ]
                },
                headers={"Authorization": f"Bearer {api_key}"}
            )

            if step2_resp.status_code != 200:
                raise Exception(f"Step 2 failed with code {step2_resp.status_code}: {step2_resp.text}")

            translations = json.loads(step2_resp.json()["choices"][0]["message"]["content"])

        return {
            "success": True,
            "original": req.text,
            "analysis": analysis,
            "translations": translations
        }
    except Exception as err:
        logger.error(f"Pipeline Error: {err}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Translation pipeline failed",
                "error": str(err)
            }
        )

@router.get("/list")
async def get_translate_languages():
    return {"success": True, "languages": SUPPORTED_LANGUAGES}
