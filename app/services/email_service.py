import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import httpx
from app.core.config import settings

def render_template(template_path: str, data: Dict[str, Any]) -> str:
    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        full_path = (base_dir / template_path).resolve()
        if not full_path.exists():
            full_path = (base_dir / "app" / template_path).resolve()

        with open(full_path, "r", encoding="utf-8") as f:
            template = f.read()

        for k, v in data.items():
            val = str(v) if v is not None else "Không xác định"
            template = re.sub(rf"\{{\{{\s*{re.escape(k)}\s*\}}\}}", val, template)
        return template
    except Exception as e:
        return ""

async def send_notification_email(
    to: Union[str, List[str]],
    subject: str,
    html: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not to or not subject or not html:
        raise ValueError("Thiếu thông tin bắt buộc: to, subject, hoặc html")

    api_key = settings.RESEND_API_KEY
    if not api_key:
        return {"id": "mock_id", "warning": "RESEND_API_KEY is missing"}

    from_email = settings.EMAIL_FROM or "Elyriax <onboarding@resend.dev>"
    recipients = [to] if isinstance(to, str) else to

    payload = {
        "from": from_email,
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        data = res.json()
        if res.status_code >= 400 or "error" in data:
            err_msg = data.get("error", {}).get("message") or data.get("message") or str(data)
            raise ValueError(err_msg)
        return data
