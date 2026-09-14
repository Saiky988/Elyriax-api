from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.cart_service import add_to_cart, clear_cart, get_cart, remove_cart_item, update_cart_item

router = APIRouter()

@router.get("")
@router.get("/")
async def get_cart_endpoint(user: dict = Depends(verify_token)):
    try:
        cart = await get_cart(user["id"])
        return send_success("Lấy giỏ hàng thành công", cart)
    except Exception as e:
        return send_error(str(e), 500)

@router.post("/items")
async def add_item_endpoint(request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        product_code = body.get("product_code")
        quantity = body.get("quantity", 1)
        if not product_code:
            return send_error("Thiếu product_code", 400)
        cart = await add_to_cart(user["id"], product_code, quantity)
        return send_success("Thêm vào giỏ hàng thành công", cart)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.patch("/items/{item_id}")
async def update_item_endpoint(item_id: int, request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        quantity = body.get("quantity")
        if quantity is None:
            return send_error("Thiếu số lượng", 400)
        cart = await update_cart_item(user["id"], item_id, quantity)
        return send_success("Cập nhật số lượng thành công", cart)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("/items/{item_id}")
async def remove_item_endpoint(item_id: int, user: dict = Depends(verify_token)):
    try:
        cart = await remove_cart_item(user["id"], item_id)
        return send_success("Xóa sản phẩm khỏi giỏ thành công", cart)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("")
@router.delete("/")
async def clear_cart_endpoint(user: dict = Depends(verify_token)):
    try:
        cart = await clear_cart(user["id"])
        return send_success("Xóa toàn bộ giỏ hàng thành công", cart)
    except Exception as e:
        return send_error(str(e), 500)
