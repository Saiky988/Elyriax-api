from typing import Any, Dict, List
from app.core.database import execute, fetch_all, fetch_one

async def get_wishlist(user_id: int) -> List[Dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT 
            w.id AS wishlist_id,
            p.product_code,
            p.name,
            p.slug,
            p.price,
            p.stock,
            p.delivery_type,
            p.status,
            p.thumbnail,
            w.created_at
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        WHERE w.user_id = %s AND p.status != 'disabled'
        ORDER BY w.created_at DESC
        """,
        (user_id,),
    )
    result = []
    for item in rows:
        result.append({
            "wishlist_id": item["wishlist_id"],
            "product_code": item["product_code"],
            "name": item["name"],
            "slug": item["slug"],
            "price": float(item["price"]),
            "stock": int(item["stock"]),
            "delivery_type": item["delivery_type"],
            "status": item["status"],
            "thumbnail": item["thumbnail"],
            "created_at": item["created_at"].isoformat() if item["created_at"] and hasattr(item["created_at"], "isoformat") else str(item["created_at"]),
        })
    return result

async def add_to_wishlist(user_id: int, product_code: str) -> List[Dict[str, Any]]:
    product = await fetch_one(
        "SELECT id FROM products WHERE product_code = %s AND status != 'disabled'",
        (product_code,),
    )
    if not product:
        raise ValueError("Sản phẩm không tồn tại")

    await execute(
        "INSERT IGNORE INTO wishlist (user_id, product_id) VALUES (%s, %s)",
        (user_id, product["id"]),
    )
    return await get_wishlist(user_id)

async def remove_from_wishlist(user_id: int, product_code: str) -> List[Dict[str, Any]]:
    product = await fetch_one("SELECT id FROM products WHERE product_code = %s", (product_code,))
    if not product:
        raise ValueError("Sản phẩm không tồn tại")

    await execute(
        "DELETE FROM wishlist WHERE user_id = %s AND product_id = %s",
        (user_id, product["id"]),
    )
    return await get_wishlist(user_id)
