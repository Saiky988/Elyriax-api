from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Request
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.order_service import cancel_order, checkout, get_order_by_id, get_orders

router = APIRouter()

@router.post("")
@router.post("/")
async def checkout_endpoint(user: dict = Depends(verify_token)):
    try:
        data = await checkout(user["id"])
        return send_success("Thanh toán đơn hàng thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("")
@router.get("/")
async def get_orders_endpoint(
    request: Request,
    page: int = 1,
    limit: int = 10,
    status: Optional[str] = None,
    user: dict = Depends(verify_token),
):
    try:
        data = await get_orders(user["id"], {"page": page, "limit": limit, "status": status})
        return send_success("Lấy danh sách đơn hàng thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/{order_id}")
async def get_order_by_id_endpoint(order_id: int, user: dict = Depends(verify_token)):
    try:
        data = await get_order_by_id(user["id"], order_id)
        return send_success("Lấy chi tiết đơn hàng thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 404)
    except Exception as e:
        return send_error(str(e), 500)

@router.post("/{order_id}/cancel")
async def cancel_order_endpoint(order_id: int, user: dict = Depends(verify_token)):
    try:
        data = await cancel_order(user["id"], order_id)
        return send_success("Hủy đơn hàng thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)
