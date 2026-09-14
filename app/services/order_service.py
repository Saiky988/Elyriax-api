import math
from typing import Any, Dict, Optional
from app.core.database import get_connection, fetch_one, fetch_all
from app.core.security import generate_order_code, generate_transaction_code

async def get_order_by_id(user_id: int, order_id: int) -> Dict[str, Any]:
    order = await fetch_one(
        """
        SELECT id, order_code, subtotal, total, currency, status, created_at, completed_at 
        FROM orders WHERE id = %s AND user_id = %s
        """,
        (order_id, user_id),
    )
    if not order:
        raise ValueError("Đơn hàng không tồn tại")

    order_items = await fetch_all(
        """
        SELECT id, product_id, product_code, product_name, quantity, unit_price, subtotal, delivery_type 
        FROM order_items WHERE order_id = %s
        """,
        (order_id,),
    )

    delivered_items = await fetch_all(
        """
        SELECT id, product_id, content, identifier 
        FROM product_items WHERE order_id = %s
        """,
        (order_id,),
    )

    formatted_items = []
    for item in order_items:
        items_belong = [
            {"id": di["id"], "identifier": di["identifier"], "content": di["content"]}
            for di in delivered_items
            if di["product_id"] == item["product_id"]
        ]
        formatted_items.append({
            "product_code": item["product_code"],
            "product_name": item["product_name"],
            "quantity": item["quantity"],
            "unit_price": float(item["unit_price"]),
            "subtotal": float(item["subtotal"]),
            "delivery_type": item["delivery_type"],
            "items": items_belong if item["delivery_type"] == "automatic" else [],
        })

    res = dict(order)
    res["subtotal"] = float(res["subtotal"])
    res["total"] = float(res["total"])
    res["created_at"] = res["created_at"].isoformat() if res["created_at"] and hasattr(res["created_at"], "isoformat") else str(res["created_at"])
    res["completed_at"] = res["completed_at"].isoformat() if res["completed_at"] and hasattr(res["completed_at"], "isoformat") else (str(res["completed_at"]) if res["completed_at"] else None)
    res["items"] = formatted_items
    return res

async def checkout(user_id: int) -> Dict[str, Any]:
    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                # 1. Lock and retrieve cart items
                await cur.execute(
                    """
                    SELECT ci.id AS cart_item_id, ci.product_id, ci.quantity, 
                           p.product_code, p.name AS product_name, p.price, p.stock, p.delivery_type, p.status
                    FROM cart_items ci
                    JOIN products p ON ci.product_id = p.id
                    WHERE ci.user_id = %s FOR UPDATE
                    """,
                    (user_id,),
                )
                cart_items = await cur.fetchall()
                if not cart_items:
                    raise ValueError("Giỏ hàng trống")

                # 2. Check product validity & available inventory
                total_amount = 0.0
                products_to_process = []

                for item in cart_items:
                    if item["status"] != "active":
                        raise ValueError(f"Sản phẩm \"{item['product_name']}\" hiện đã ngừng kinh doanh")

                    unit_price = float(item["price"])
                    qty = int(item["quantity"])
                    item_subtotal = unit_price * qty
                    total_amount += item_subtotal

                    # Lock available items in stock
                    await cur.execute(
                        """
                        SELECT id, content, identifier 
                        FROM product_items 
                        WHERE product_id = %s AND status = 'available' 
                        LIMIT %s FOR UPDATE
                        """,
                        (item["product_id"], qty),
                    )
                    available_items = await cur.fetchall()
                    if len(available_items) < qty:
                        raise ValueError(f"Sản phẩm \"{item['product_name']}\" không đủ số lượng trong kho (còn {len(available_items)})")

                    products_to_process.append({
                        **item,
                        "subtotal": item_subtotal,
                        "assigned_items": available_items,
                    })

                # 3. Lock Wallet and check balance
                await cur.execute(
                    "SELECT id, balance, total_spent FROM wallets WHERE user_id = %s FOR UPDATE",
                    (user_id,),
                )
                wallet = await cur.fetchone()
                if not wallet:
                    raise ValueError("Ví người dùng không tồn tại")

                balance_before = float(wallet["balance"])
                if balance_before < total_amount:
                    raise ValueError(f"Số dư ví không đủ (Hiện có: {balance_before:,.0f} VND, Cần: {total_amount:,.0f} VND)")

                balance_after = balance_before - total_amount

                # 4. Deduct balance
                await cur.execute(
                    "UPDATE wallets SET balance = balance - %s, total_spent = total_spent + %s WHERE id = %s",
                    (total_amount, total_amount, wallet["id"]),
                )

                # 5. Insert order
                order_code = generate_order_code()
                await cur.execute(
                    """
                    INSERT INTO orders (order_code, user_id, wallet_id, subtotal, total, currency, status, completed_at) 
                    VALUES (%s, %s, %s, %s, %s, 'VND', 'completed', CURRENT_TIMESTAMP)
                    """,
                    (order_code, user_id, wallet["id"], total_amount, total_amount),
                )
                order_id = cur.lastrowid

                # 6. Insert order items and assign inventory items
                for p_item in products_to_process:
                    await cur.execute(
                        """
                        INSERT INTO order_items 
                        (order_id, product_id, product_code, product_name, quantity, unit_price, subtotal, delivery_type) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            order_id,
                            p_item["product_id"],
                            p_item["product_code"],
                            p_item["product_name"],
                            p_item["quantity"],
                            p_item["price"],
                            p_item["subtotal"],
                            p_item["delivery_type"],
                        ),
                    )

                    assigned_ids = [ai["id"] for ai in p_item["assigned_items"]]
                    format_strings = ",".join(["%s"] * len(assigned_ids))
                    await cur.execute(
                        f"""
                        UPDATE product_items 
                        SET status = 'sold', order_id = %s, sold_at = CURRENT_TIMESTAMP 
                        WHERE id IN ({format_strings})
                        """,
                        [order_id, *assigned_ids],
                    )

                    # Synchronize stock
                    await cur.execute(
                        """
                        UPDATE products 
                        SET stock = (SELECT COUNT(id) FROM product_items WHERE product_id = %s AND status = 'available') 
                        WHERE id = %s
                        """,
                        (p_item["product_id"], p_item["product_id"]),
                    )

                # 7. Record transaction
                tx_code = generate_transaction_code()
                await cur.execute(
                    """
                    INSERT INTO transactions 
                    (transaction_code, user_id, wallet_id, type, amount, balance_before, balance_after, status, payment_method, reference_id, description, completed_at) 
                    VALUES (%s, %s, %s, 'purchase', %s, %s, %s, 'completed', 'wallet', %s, %s, CURRENT_TIMESTAMP)
                    """,
                    (tx_code, user_id, wallet["id"], total_amount, balance_before, balance_after, order_code, f"Thanh toán đơn hàng {order_code}"),
                )

                # 8. Clear cart
                await cur.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    return await get_order_by_id(user_id, order_id)

async def get_orders(user_id: int, query: Dict[str, Any]) -> Dict[str, Any]:
    page = int(query.get("page", 1) or 1)
    limit = int(query.get("limit", 10) or 10)
    status = query.get("status")
    offset = (page - 1) * limit

    sql = "SELECT id, order_code, subtotal, total, currency, status, created_at, completed_at FROM orders WHERE user_id = %s"
    params = [user_id]
    if status:
        sql += " AND status = %s"
        params.append(status)

    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    items = await fetch_all(sql, tuple(params))
    for it in items:
        it["subtotal"] = float(it["subtotal"])
        it["total"] = float(it["total"])
        it["created_at"] = it["created_at"].isoformat() if it["created_at"] and hasattr(it["created_at"], "isoformat") else str(it["created_at"])
        it["completed_at"] = it["completed_at"].isoformat() if it["completed_at"] and hasattr(it["completed_at"], "isoformat") else (str(it["completed_at"]) if it["completed_at"] else None)

    count_sql = "SELECT COUNT(id) as total FROM orders WHERE user_id = %s"
    count_params = [user_id]
    if status:
        count_sql += " AND status = %s"
        count_params.append(status)

    count_row = await fetch_one(count_sql, tuple(count_params))
    total = count_row["total"] if count_row else 0

    return {
        "items": items,
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": math.ceil(total / limit) if limit > 0 else 1,
        },
    }

async def cancel_order(user_id: int, order_id: int) -> Dict[str, Any]:
    order = await fetch_one("SELECT id, status FROM orders WHERE id = %s AND user_id = %s", (order_id, user_id))
    if not order:
        raise ValueError("Đơn hàng không tồn tại")

    if order["status"] == "completed":
        raise ValueError("Không thể hủy đơn hàng đã hoàn tất. Vui lòng liên hệ hỗ trợ.")
    if order["status"] == "cancelled":
        raise ValueError("Đơn hàng đã được hủy trước đó.")

    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s", (order_id,))
    return {"id": order_id, "status": "cancelled"}
