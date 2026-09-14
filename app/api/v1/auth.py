from urllib.parse import quote, urlencode
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
import httpx
from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import verify_token
from app.core.security import create_jwt_token
from app.services.api_key_service import (
    delete_api_key,
    get_api_key_info,
    get_or_create_api_key,
)
from app.services.auth_service import handle_oauth_login_or_link
from app.services.session_service import (
    create_session,
    revoke_all_user_sessions,
    revoke_session,
)

router = APIRouter()

BASE_URL = f"{settings.BASE_URL}/v1/auth"
FRONTEND_URL = settings.FRONTEND_URL or "https://apis.elyriax.com"

@router.get("/login/{provider}")
async def oauth_login(provider: str, token: str = ""):
    state_param = token if token else "login"

    if provider == "discord":
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": f"{BASE_URL}/discord/callback",
            "response_type": "code",
            "scope": "identify email",
            "state": state_param,
        }
        auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    elif provider == "google":
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": f"{BASE_URL}/google/callback",
            "response_type": "code",
            "scope": "profile email",
            "state": state_param,
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    elif provider == "github":
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": f"{BASE_URL}/github/callback",
            "scope": "user:email",
            "state": state_param,
        }
        auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    else:
        return JSONResponse(status_code=400, content={"error": "Provider không hợp lệ!"})

    return RedirectResponse(auth_url)

@router.get("/github/callback")
async def github_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/?error=GitHub_Login_Failed")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": f"{BASE_URL}/github/callback",
                },
            )
            token_data = token_res.json()
            if "error" in token_data:
                raise ValueError(token_data.get("error_description", token_data["error"]))

            access_token = token_data["access_token"]
            auth_headers = {"Authorization": f"Bearer {access_token}"}

            user_res = await client.get("https://api.github.com/user", headers=auth_headers)
            user_data = user_res.json()

            email_res = await client.get("https://api.github.com/user/emails", headers=auth_headers)
            email_data = email_res.json()

        primary_email = None
        if isinstance(email_data, list):
            for e in email_data:
                if e.get("primary"):
                    primary_email = e.get("email")
                    break

        profile = {
            "provider": "github",
            "id": str(user_data["id"]),
            "email": primary_email,
            "name": user_data.get("name") or user_data.get("login"),
            "avatar": user_data.get("avatar_url"),
        }

        result = await handle_oauth_login_or_link(profile, state)
        if result["action"] == "linked":
            return RedirectResponse(f"{FRONTEND_URL}/?link=success&provider=github")

        session_token = await create_session(result["user"]["id"], request, remember_me=True)
        token_payload = {
            "id": result["user"]["id"],
            "username": result["user"]["username"],
            "email": result["user"].get("email"),
            "avatar": result["user"].get("avatar"),
            "providers": result["user"].get("providers", []),
        }
        jwt_token = create_jwt_token(token_payload, expires_days=365)

        response = RedirectResponse(f"{FRONTEND_URL}/?token={jwt_token}")
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
            max_age=365 * 24 * 60 * 60,
        )
        return response
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/?error={quote(str(e))}")

@router.get("/discord/callback")
async def discord_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/?error=Discord_Login_Failed")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://discord.com/api/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_id": settings.DISCORD_CLIENT_ID,
                    "client_secret": settings.DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{BASE_URL}/discord/callback",
                },
            )
            token_data = token_res.json()
            if "error" in token_data:
                raise ValueError(token_data.get("error_description", token_data["error"]))

            access_token = token_data["access_token"]
            user_res = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_data = user_res.json()

        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png"
            if user_data.get("avatar")
            else None
        )
        profile = {
            "provider": "discord",
            "id": user_data["id"],
            "email": user_data.get("email"),
            "name": user_data.get("global_name") or user_data.get("username"),
            "avatar": avatar_url,
        }

        result = await handle_oauth_login_or_link(profile, state)
        if result["action"] == "linked":
            return RedirectResponse(f"{FRONTEND_URL}/?link=success&provider=discord")

        session_token = await create_session(result["user"]["id"], request, remember_me=True)
        token_payload = {
            "id": result["user"]["id"],
            "username": result["user"]["username"],
            "email": result["user"].get("email"),
            "avatar": result["user"].get("avatar"),
            "providers": result["user"].get("providers", []),
        }
        jwt_token = create_jwt_token(token_payload, expires_days=365)

        response = RedirectResponse(f"{FRONTEND_URL}/?token={jwt_token}")
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
            max_age=365 * 24 * 60 * 60,
        )
        return response
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/?error={quote(str(e))}")

@router.get("/google/callback")
async def google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}/?error=Google_Login_Failed")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": f"{BASE_URL}/google/callback",
                },
            )
            token_data = token_res.json()
            if "error" in token_data:
                raise ValueError(token_data.get("error_description", token_data["error"]))

            access_token = token_data["access_token"]
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_data = user_res.json()

        profile = {
            "provider": "google",
            "id": user_data["id"],
            "email": user_data.get("email"),
            "name": user_data.get("name"),
            "avatar": user_data.get("picture"),
        }

        result = await handle_oauth_login_or_link(profile, state)
        if result["action"] == "linked":
            return RedirectResponse(f"{FRONTEND_URL}/?link=success&provider=google")

        session_token = await create_session(result["user"]["id"], request, remember_me=True)
        token_payload = {
            "id": result["user"]["id"],
            "username": result["user"]["username"],
            "email": result["user"].get("email"),
            "avatar": result["user"].get("avatar"),
            "providers": result["user"].get("providers", []),
        }
        jwt_token = create_jwt_token(token_payload, expires_days=365)

        response = RedirectResponse(f"{FRONTEND_URL}/?token={jwt_token}")
        response.set_cookie(
            key="session",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
            max_age=365 * 24 * 60 * 60,
        )
        return response
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}/?error={quote(str(e))}")

@router.post("/unlink/{provider}")
async def unlink_provider(provider: str, user: dict = Depends(verify_token)):
    user_id = user["id"]
    try:
        links = await fetch_all("SELECT provider FROM user_oauth_accounts WHERE user_id = %s", (user_id,))
        u = await fetch_one("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        has_password = (u.get("password_hash") is not None) if u else False

        total_methods = len(links) + (1 if has_password else 0)
        if total_methods <= 1:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Không thể hủy liên kết. Đây là phương thức đăng nhập duy nhất của bạn!"},
            )

        provider_exists = any(l["provider"] == provider for l in links)
        if not provider_exists:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Tài khoản chưa được liên kết phương thức này."},
            )

        await execute("DELETE FROM user_oauth_accounts WHERE user_id = %s AND provider = %s", (user_id, provider))
        return {"success": True, "message": f"Đã hủy liên kết {provider} thành công."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống."})

@router.post("/apikey")
async def create_api_key_endpoint(user: dict = Depends(verify_token)):
    try:
        return await get_or_create_api_key(user["id"])
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống."})

@router.get("/apikey")
async def get_api_key_endpoint(user: dict = Depends(verify_token)):
    try:
        info = await get_api_key_info(user["id"])
        if not info:
            return JSONResponse(status_code=404, content={"success": False, "error": "Chưa có API Key"})
        return {"success": True, "data": info}
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống."})

@router.delete("/apikey")
async def delete_api_key_endpoint(user: dict = Depends(verify_token)):
    try:
        deleted = await delete_api_key(user["id"])
        if not deleted:
            return JSONResponse(status_code=404, content={"success": False, "error": "Chưa có API Key để xóa"})
        return {"success": True, "message": "Đã xóa API Key thành công"}
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống."})

@router.post("/logout")
async def logout(request: Request, response: Response):
    try:
        session_token = request.cookies.get("session")
        if session_token:
            await revoke_session(session_token)
        response.delete_cookie("session", path="/")
        return {"success": True, "message": "Đăng xuất thành công"}
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống"})

@router.post("/logout-all")
async def logout_all(response: Response, user: dict = Depends(verify_token)):
    try:
        await revoke_all_user_sessions(user["id"])
        response.delete_cookie("session", path="/")
        return {"success": True, "message": "Đã đăng xuất khỏi toàn bộ thiết bị"}
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống"})
