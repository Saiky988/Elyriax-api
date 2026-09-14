import io
from urllib.parse import quote
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
import httpx
import jwt
from PIL import Image
from app.core.config import settings
from app.core.deps import verify_sepay_webhook
from app.services.wallet_service import process_sepay_webhook

router = APIRouter()
cached_logo_bytes: Optional[bytes] = None

@router.post("/sepay/webhook", dependencies=[Depends(verify_sepay_webhook)])
async def sepay_webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Fire and forget processing
    background_tasks.add_task(process_sepay_webhook, payload)
    return {"success": True}

@router.get("/qr")
async def generate_qr(token: str = Query(..., description="JWT token containing amount and content")):
    global cached_logo_bytes
    if not token:
        return Response("Missing token", status_code=400)

    try:
        decoded = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        amount = decoded["amount"]
        content = decoded["content"]
    except Exception:
        return Response("Token invalid or expired", status_code=403)

    bank_id = settings.BANK_ID or "MB"
    account_no = settings.BANK_ACCOUNT_NO
    account_name = settings.BANK_ACCOUNT_NAME
    logo_url = "https://www.elyriax.com/assets/logoqr.png"

    try:
        viet_qr_url = (
            f"https://img.vietqr.io/image/{bank_id}-{account_no}-qr_only.png"
            f"?amount={amount}&addInfo={quote(str(content))}&accountName={quote(str(account_name))}"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            qr_res = await client.get(viet_qr_url)
            qr_bytes = qr_res.content

            if cached_logo_bytes is None:
                try:
                    logo_res = await client.get(logo_url)
                    if logo_res.status_code == 200:
                        cached_logo_bytes = logo_res.content
                except Exception:
                    pass

        qr_img = Image.open(io.BytesIO(qr_bytes)).convert("RGBA")
        qr_img = qr_img.resize((400, 400), Image.Resampling.LANCZOS)

        if cached_logo_bytes:
            try:
                logo_img = Image.open(io.BytesIO(cached_logo_bytes)).convert("RGBA")
                logo_img = logo_img.resize((60, 60), Image.Resampling.LANCZOS)
                pos = ((400 - 60) // 2, (400 - 60) // 2)
                qr_img.paste(logo_img, pos, mask=logo_img)
            except Exception:
                pass

        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        png_data = buf.getvalue()

        return Response(
            content=png_data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"},
        )
    except Exception as e:
        return Response("Internal Server Error", status_code=500)
