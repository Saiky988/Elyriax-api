from typing import Any, Dict, Optional
from fastapi import APIRouter, Request
from app.core.response import send_error, send_success
from app.services.product_service import get_product_by_code, get_public_products

router = APIRouter()

@router.get("")
@router.get("/")
async def get_public_products_endpoint(
    request: Request,
    page: int = 1,
    limit: int = 12,
    search: Optional[str] = None,
    category: Optional[str] = None,
    sort: Optional[str] = "DESC",
):
    try:
        data = await get_public_products({
            "page": page,
            "limit": limit,
            "search": search,
            "category": category,
            "sort": sort,
        })
        return send_success("Lấy danh sách sản phẩm thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/{product_code}")
async def get_product_detail_endpoint(product_code: str):
    try:
        data = await get_product_by_code(product_code)
        return send_success("Lấy chi tiết sản phẩm thành công", data)
    except ValueError as ve:
        return send_error(str(ve), 404)
    except Exception as e:
        return send_error(str(e), 500)
