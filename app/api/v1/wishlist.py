from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.wishlist_service import add_to_wishlist, get_wishlist, remove_from_wishlist

router = APIRouter()

@router.get("")
@router.get("/")
async def get_wishlist_endpoint(user: dict = Depends(verify_token)):
    try:
        data = await get_wishlist(user["id"])
        return send_success("Lấy danh sách yêu thích thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.post("/items")
async def add_wishlist_item_endpoint(request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        product_code = body.get("product_code")
        if not product_code:
            return send_error("Thiếu product_code", 400)
        data = await add_to_wishlist(user["id"], product_code)
        return send_success("Đã thêm vào danh sách yêu thích", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("/items/{product_code}")
async def remove_wishlist_item_endpoint(product_code: str, user: dict = Depends(verify_token)):
    try:
        data = await remove_from_wishlist(user["id"], product_code)
        return send_success("Đã xóa khỏi danh sách yêu thích", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)
