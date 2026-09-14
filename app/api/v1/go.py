from typing import Any, Dict, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from app.core.config import settings
from app.services.go_service import create_go_link, get_go_metadata, resolve_redirect

router = APIRouter()

def verify_go_admin(request: Request):
    admin_user = request.headers.get("x-admin-user")
    admin_pass = request.headers.get("x-admin-pass")
    auth_header = request.headers.get("authorization")

    expected_user = settings.ADMIN_USER or "elyriax"
    expected_pass = settings.ADMIN_PASS or "ElyriaxDeptrai"
    expected_token = settings.ADMIN_TOKEN

    if admin_user == expected_user and admin_pass == expected_pass:
        return True

    if expected_token and auth_header:
        token = auth_header.replace("Bearer ", "").replace("bearer ", "").strip()
        if token == expected_token:
            return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"success": False, "error": "Unauthorized"},
    )

@router.post("/v1/go/create")
async def create_link_endpoint(request: Request):
    verify_go_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    url = body.get("url")
    device = body.get("device")
    expires_in = body.get("expiresIn", 3600)

    if not url or not device:
        return JSONResponse(status_code=400, content={"success": False, "error": "url and device are required."})

    try:
        result = create_go_link(url=url, device=device, expires_in=expires_in)
        return JSONResponse(status_code=201, content=result)
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"success": False, "error": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "Internal server error"})

@router.get("/v1/go/{link_id}")
async def get_link_metadata_endpoint(link_id: str, request: Request):
    verify_go_admin(request)
    item = get_go_metadata(link_id)
    if not item:
        return JSONResponse(status_code=404, content={"success": False, "error": "Link not found"})
    return item

@router.get("/n/{device}/{link_id}")
async def redirect_endpoint(device: str, link_id: str):
    destination = resolve_redirect(device, link_id)
    if not destination:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "LINK_EXPIRED_OR_INVALID",
                "message": "This link is no longer available or has expired.",
            },
        )
    return RedirectResponse(destination, status_code=302)
