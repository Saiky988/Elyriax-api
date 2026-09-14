from typing import Any, Dict
from app.core.database import execute, fetch_all, fetch_one, get_connection

async def get_cart(user_id: int) -> Dict[str, Any]:
    items = await fetch_all(
        """
        SELECT 
            ci.id,
            ci.product_id,
            p.product_code,
            p.name AS product_name,
            p.slug,
            p.price AS unit_price,
            ci.quantity,
            p.stock,
            p.delivery_type,
            p.status AS product_status,
            p.thumbnail,
            (p.price * ci.quantity) AS subtotal
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.user_id = %s
        ORDER BY ci.created_at DESC
        """,
        (user_id,),
    )

    total = 0.0
    total_items = 0
    formatted_items = []

    for item in items:
        subtotal = float(item["subtotal"] or 0)
        unit_price = float(item["unit_price"] or 0)
        qty = int(item["quantity"])
        stock = int(item["stock"])
        is_active = item["product_status"] == "active"

        if is_active:
            total += subtotal
            total_items += qty

        formatted_items.append({
            "id": item["id"],
            "product_code": item["product_code"],
            "product_name": item["product_name"],
            "slug": item["slug"],
            "unit_price": f"{unit_price:.2f}",
            "quantity": qty,
            "stock": stock,
            "delivery_type": item["delivery_type"],
            "thumbnail": item["thumbnail"],
            "subtotal": f"{subtotal:.2f}",
            "is_available": is_active and stock >= qty,
        })

    return {
        "items": formatted_items,
        "summary": {
            "total_items": total_items,
            "total_amount": f"{total:.2f}",
            "currency": "VND",
        },
    }

async def add_to_cart(user_id: int, product_code: str, quantity: int = 1) -> Dict[str, Any]:
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        raise ValueError("Số lượng sản phẩm không hợp lệ")

    if qty <= 0:
        raise ValueError("Số lượng sản phẩm không hợp lệ")

    product = await fetch_one(
        "SELECT id, name, price, stock, status FROM products WHERE product_code = %s",
        (product_code,),
    )
    if not product or product["status"] != "active":
        raise ValueError("Sản phẩm không tồn tại hoặc đã ngừng kinh doanh")

    existing = await fetch_one(
        "SELECT id, quantity FROM cart_items WHERE user_id = %s AND product_id = %s",
        (user_id, product["id"]),
    )

    new_quantity = (existing["quantity"] + qty) if existing else qty
    if new_quantity > int(product["stock"]):
        raise ValueError(f"Kho hàng chỉ còn {product['stock']} sản phẩm")

    if existing:
        await execute("UPDATE cart_items SET quantity = %s WHERE id = %s", (new_quantity, existing["id"]))
    else:
        await execute("INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s, %s, %s)", (user_id, product["id"], qty))

    return await get_cart(user_id)

async def update_cart_item(user_id: int, cart_item_id: int, quantity: int) -> Dict[str, Any]:
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        raise ValueError("Số lượng phải lớn hơn 0")

    if qty <= 0:
        raise ValueError("Số lượng phải lớn hơn 0")

    item = await fetch_one(
        """
        SELECT ci.id, ci.product_id, p.stock, p.status 
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.id = %s AND ci.user_id = %s
        """,
        (cart_item_id, user_id),
    )
    if not item:
        raise ValueError("Mục giỏ hàng không tồn tại")

    if item["status"] != "active":
        raise ValueError("Sản phẩm này hiện không khả dụng")

    if qty > int(item["stock"]):
        raise ValueError(f"Kho hàng chỉ còn {item['stock']} sản phẩm")

    await execute("UPDATE cart_items SET quantity = %s WHERE id = %s", (qty, cart_item_id))
    return await get_cart(user_id)

async def remove_cart_item(user_id: int, cart_item_id: int) -> Dict[str, Any]:
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM cart_items WHERE id = %s AND user_id = %s", (cart_item_id, user_id))
            if cur.rowcount == 0:
                raise ValueError("Mục giỏ hàng không tồn tại")

    return await get_cart(user_id)

async def clear_cart(user_id: int) -> Dict[str, Any]:
    await execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
    return {"items": [], "summary": {"total_items": 0, "total_amount": "0.00", "currency": "VND"}}
