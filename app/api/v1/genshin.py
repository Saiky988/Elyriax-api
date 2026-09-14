from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from app.core.database import fetch_one
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.genshin.account_service import (
    add_account,
    delete_account,
    get_account_by_id,
    get_accounts,
    get_ready_genshin_payload,
    update_account,
)
from app.services.genshin.banner import get_banners
from app.services.genshin.checkin import check_in_daily
from app.services.genshin.checkin_list import get_check_in_list
from app.services.genshin.codes import get_all_codes
from app.services.genshin.daily_note import get_daily_note
from app.services.genshin.redeem import redeem_code
from app.services.genshin.stats import get_role_and_stats

router = APIRouter()

async def resolve_account_payload(user_id: int, account_id: Optional[int] = None) -> Dict[str, Any]:
    if account_id:
        return await get_ready_genshin_payload(user_id, account_id)

    row = await fetch_one(
        'SELECT id FROM genshin_accounts WHERE user_id = %s AND is_default = TRUE AND status = "active"',
        (user_id,),
    )
    if not row:
        raise ValueError("Chưa chọn tài khoản Genshin mặc định. Vui lòng thêm tài khoản hoặc chọn account_id!")

    return await get_ready_genshin_payload(user_id, row["id"])

# ----------------------------------------------------
# GENSHIN PUBLIC & GENERAL QUERY ENDPOINTS
# ----------------------------------------------------

@router.get("")
@router.get("/")
async def genshin_get_router(type: Optional[str] = Query(None)):
    if not type or type not in ["banner", "codes"]:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Missing or invalid query. Use ?type=banner or ?type=codes"},
        )

    try:
        if type == "banner":
            banners = await get_banners()
            return {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": banners,
            }

        if type == "codes":
            cards = await get_all_codes()
            total_codes_count = sum(len(c.get("codes", [])) for c in cards)
            return {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count": total_codes_count,
                "cards": cards,
            }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to fetch data.", "error": str(e)},
        )

@router.post("")
@router.post("/")
async def genshin_post_router(request: Request, type: Optional[str] = Query(None)):
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not type or type not in ["checkindaily", "redeemcode"]:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing or invalid query"})

    try:
        if type == "checkindaily":
            return await check_in_daily(body)
        if type == "redeemcode":
            return await redeem_code(body)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.post("/role-stats")
async def post_role_stats(request: Request):
    try:
        body = await request.json()
        return await get_role_and_stats(body)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.post("/daily-note")
async def post_daily_note(request: Request):
    try:
        body = await request.json()
        return await get_daily_note(body)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# ----------------------------------------------------
# GENSHIN USER STATS & ACTIONS (AUTHENTICATED)
# ----------------------------------------------------

@router.get("/stats")
async def get_default_stats(user: dict = Depends(verify_token)):
    try:
        payload = await resolve_account_payload(user["id"])
        result = await get_role_and_stats(payload)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.get("/accounts/{account_id}/stats")
async def get_account_stats(account_id: int, user: dict = Depends(verify_token)):
    try:
        payload = await resolve_account_payload(user["id"], account_id)
        result = await get_role_and_stats(payload)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.get("/accounts/{account_id}/daily-note")
async def get_account_daily_note(account_id: int, user: dict = Depends(verify_token)):
    try:
        payload = await resolve_account_payload(user["id"], account_id)
        result = await get_daily_note(payload)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.get("/accounts/{account_id}/checkin-list")
async def get_account_checkin_list(account_id: int, user: dict = Depends(verify_token)):
    try:
        payload = await resolve_account_payload(user["id"], account_id)
        result = await get_check_in_list(payload)
        if not result.get("ok"):
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@router.post("/accounts/{account_id}/checkin")
async def post_account_checkin(account_id: int, user: dict = Depends(verify_token)):
    try:
        payload = await resolve_account_payload(user["id"], account_id)
        result = await check_in_daily(payload)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# ----------------------------------------------------
# GENSHIN ACCOUNTS MANAGEMENT (CRUD)
# ----------------------------------------------------

@router.post("/accounts")
async def add_account_endpoint(request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        cookie = body.get("cookie")
        uid = body.get("uid")
        server = body.get("server")
        if not cookie or not uid or not server:
            return send_error("Thiếu thông tin cookie, uid hoặc server.", 400)

        data = await add_account(user["id"], {"cookie": cookie, "uid": uid, "server": server})
        return send_success("Thêm tài khoản Genshin thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/accounts")
async def get_accounts_endpoint(user: dict = Depends(verify_token)):
    try:
        data = await get_accounts(user["id"])
        return send_success("Lấy danh sách tài khoản thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/accounts/{account_id}")
async def get_account_detail_endpoint(account_id: int, user: dict = Depends(verify_token)):
    try:
        data = await get_account_by_id(user["id"], account_id)
        return send_success("Lấy chi tiết tài khoản thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 404)
    except Exception as e:
        return send_error(str(e), 500)

@router.patch("/accounts/{account_id}")
async def update_account_endpoint(account_id: int, request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        await update_account(user["id"], account_id, body)
        return send_success("Cập nhật cài đặt tài khoản thành công")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("/accounts/{account_id}")
async def delete_account_endpoint(account_id: int, user: dict = Depends(verify_token)):
    try:
        await delete_account(user["id"], account_id)
        return send_success("Đã xóa tài khoản khỏi hệ thống")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)
