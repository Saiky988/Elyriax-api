import re
from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.email_service import send_notification_email

router = APIRouter(dependencies=[Depends(verify_token)])

@router.post("/notify")
async def send_notification(request: Request):
    try:
        body = await request.json()
        to = body.get("to")
        subject = body.get("subject")
        html = body.get("html")
        template_data = body.get("template_data")

        if not to or not subject or not html:
            return send_error("Vui lòng cung cấp đầy đủ params: to, subject, html", 400)

        final_html = html
        if template_data and isinstance(template_data, dict):
            for k, v in template_data.items():
                final_html = re.sub(rf"\{{\{{\s*{re.escape(k)}\s*\}}\}}", str(v), final_html)

        result = await send_notification_email(to=to, subject=subject, html=final_html)
        return send_success("Gửi email thông báo thành công!", result)
    except Exception as e:
        return send_error(str(e), 500)
