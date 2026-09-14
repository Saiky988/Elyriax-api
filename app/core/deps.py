from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.responses import JSONResponse
import jwt
from app.core.config import settings
from app.core.security import decode_jwt_token
from app.services.session_service import verify_session
from app.services.api_key_service import validate_api_key

async def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    # 0. Check static admin credentials
    admin_user = request.headers.get("x-admin-user")
    admin_pass = request.headers.get("x-admin-pass")
    if admin_user and admin_pass:
        if admin_user == settings.ADMIN_USERNAME and admin_pass == settings.ADMIN_PASSWORD:
            return {"id": 1, "username": admin_user, "isStaticAdmin": True}

    # 1. Check session cookie
    session_token = request.cookies.get("session")
    if session_token:
        user = await verify_session(session_token)
        if user:
            return user

    # 2. Check JWT Bearer token
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            decoded = decode_jwt_token(token)
            return decoded
        except jwt.PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"success": False, "message": "Token không hợp lệ"},
            )

    return None

async def verify_token(request: Request) -> Dict[str, Any]:
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Chưa đăng nhập"},
        )
    request.state.user = user
    return user

async def verify_admin(request: Request, user: Dict[str, Any] = Depends(verify_token)) -> Dict[str, Any]:
    admin_user = request.headers.get("x-admin-user")
    admin_pass = request.headers.get("x-admin-pass")
    if admin_user and admin_pass:
        if admin_user == settings.ADMIN_USERNAME and admin_pass == settings.ADMIN_PASSWORD:
            return user

    if user and int(user.get("id", 0)) == 1:
        return user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"success": False, "message": "Quyền truy cập bị từ chối. Chỉ dành cho Admin!"},
    )

async def verify_api_key(request: Request) -> Dict[str, Any]:
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "Missing or wrong API Key format"},
        )

    api_key = auth_header.split(" ", 1)[1].strip()
    user_id = await validate_api_key(api_key)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "API Key is invalid or deleted"},
        )

    user = {"id": user_id}
    request.state.user = user
    return user

async def verify_sepay_webhook(request: Request):
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    expected_key = f"Apikey {settings.SEPAY_WEBHOOK_TOKEN}"
    if not auth_header or auth_header != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "Unauthorized webhook"},
        )
