from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Request
from app.core.database import fetch_one
from app.core.deps import verify_token
from app.core.response import send_error, send_success
from app.services.wallet_service import (
    create_deposit_info,
    get_or_create_wallet,
    get_transactions,
)

router = APIRouter()

@router.get("")
@router.get("/")
async def get_wallet_endpoint(user: dict = Depends(verify_token)):
    try:
        wallet = await get_or_create_wallet(user["id"])
        return send_success("Lấy thông tin ví thành công", wallet)
    except Exception as e:
        return send_error(str(e), 500)

@router.post("/deposit")
async def create_deposit_endpoint(request: Request, user: dict = Depends(verify_token)):
    try:
        body = await request.json()
        amount = body.get("amount")
        data = await create_deposit_info(user["id"], amount)
        return send_success("Tạo yêu cầu nạp tiền thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/deposit/{transaction_code}")
async def get_deposit_status_endpoint(transaction_code: str, user: dict = Depends(verify_token)):
    try:
        tx = await fetch_one(
            "SELECT status FROM transactions WHERE user_id = %s AND transaction_code = %s",
            (user["id"], transaction_code),
        )
        if not tx:
            return send_error("Không tìm thấy giao dịch", 404)
        return send_success("Trạng thái giao dịch", {"status": tx["status"]})
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/transactions")
async def get_transactions_endpoint(
    request: Request,
    page: int = 1,
    limit: int = 10,
    type: Optional[str] = None,
    status: Optional[str] = None,
    sort: Optional[str] = "DESC",
    user: dict = Depends(verify_token),
):
    try:
        data = await get_transactions(
            user["id"],
            {"page": page, "limit": limit, "type": type, "status": status, "sort": sort},
        )
        return send_success("Lấy lịch sử giao dịch thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/transactions/{tx_id}")
async def get_transaction_by_id_endpoint(tx_id: int, user: dict = Depends(verify_token)):
    try:
        tx = await fetch_one(
            "SELECT * FROM transactions WHERE user_id = %s AND id = %s",
            (user["id"], tx_id),
        )
        if not tx:
            return send_error("Giao dịch không tồn tại", 404)
        res = dict(tx)
        res["amount"] = float(res["amount"])
        if res.get("balance_before") is not None:
            res["balance_before"] = float(res["balance_before"])
        if res.get("balance_after") is not None:
            res["balance_after"] = float(res["balance_after"])
        if res.get("created_at") and hasattr(res["created_at"], "isoformat"):
            res["created_at"] = res["created_at"].isoformat()
        if res.get("completed_at") and hasattr(res["completed_at"], "isoformat"):
            res["completed_at"] = res["completed_at"].isoformat()
        return send_success("Chi tiết giao dịch", res)
    except Exception as e:
        return send_error(str(e), 500)
