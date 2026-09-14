from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request
from app.core.deps import verify_admin
from app.core.response import send_error, send_success
from app.services.product_service import (
    create_product,
    delete_product,
    delete_product_item,
    get_admin_product_items,
    import_product_items,
    update_product,
    update_product_item,
)

router = APIRouter(dependencies=[Depends(verify_admin)])

@router.post("/products")
async def create_product_endpoint(request: Request):
    try:
        body = await request.json()
        if not body.get("product_code") or not body.get("name"):
            return send_error("Thiếu thông tin product_code hoặc name", 400)
        prod_id = await create_product(body)
        return send_success("Tạo sản phẩm thành công", {"id": prod_id})
    except Exception as e:
        if "Duplicate entry" in str(e) or "ER_DUP_ENTRY" in str(e):
            return send_error("Product Code đã tồn tại", 400)
        return send_error(str(e), 500)

@router.patch("/products/{prod_id}")
async def update_product_endpoint(prod_id: int, request: Request):
    try:
        body = await request.json()
        await update_product(prod_id, body)
        return send_success("Cập nhật sản phẩm thành công")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("/products/{prod_id}")
async def delete_product_endpoint(prod_id: int):
    try:
        await delete_product(prod_id)
        return send_success("Vô hiệu hóa sản phẩm thành công")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.post("/products/{prod_id}/items/import")
async def import_items_endpoint(prod_id: int, request: Request):
    try:
        body = await request.json()
        content = body.get("content")
        if not isinstance(content, list) or len(content) == 0:
            return send_error("Dữ liệu import không hợp lệ", 400)
        result = await import_product_items(prod_id, content)
        return send_success("Import kho hàng thành công", result)
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.get("/products/{prod_id}/items")
async def get_items_endpoint(
    prod_id: int,
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    try:
        data = await get_admin_product_items(prod_id, {
            "page": page,
            "limit": limit,
            "status": status,
            "search": search,
        })
        return send_success("Lấy danh sách kho hàng thành công", data)
    except Exception as e:
        return send_error(str(e), 500)

@router.patch("/product-items/{item_id}")
async def update_product_item_endpoint(item_id: int, request: Request):
    try:
        body = await request.json()
        content = body.get("content")
        if not content:
            return send_error("Thiếu nội dung cập nhật", 400)
        await update_product_item(item_id, content)
        return send_success("Cập nhật tài nguyên thành công")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)

@router.delete("/product-items/{item_id}")
async def delete_product_item_endpoint(item_id: int):
    try:
        await delete_product_item(item_id)
        return send_success("Xóa tài nguyên thành công (Đã cập nhật Stock)")
    except ValueError as ve:
        return send_error(str(ve), 400)
    except Exception as e:
        return send_error(str(e), 500)
