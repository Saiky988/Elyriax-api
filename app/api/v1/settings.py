from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from app.core.deps import verify_token
from app.services.setting_service import get_settings, update_settings

router = APIRouter()

@router.get("")
@router.get("/")
async def get_user_settings(user: dict = Depends(verify_token)):
    try:
        data = await get_settings(user["id"])
        return {"success": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống khi lấy cài đặt."})

@router.patch("")
@router.patch("/")
async def patch_user_settings(request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not body:
        return JSONResponse(status_code=400, content={"success": False, "error": "Dữ liệu cập nhật không được để trống."})

    try:
        updated = await update_settings(user["id"], body)
        return {
            "success": True,
            "message": "Cập nhật cài đặt thành công.",
            "data": updated,
        }
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"success": False, "error": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "Lỗi hệ thống khi cập nhật cài đặt."})
