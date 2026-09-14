import math
from typing import Any, Dict, List, Optional
from app.core.database import execute, fetch_all, fetch_one, get_connection
from app.core.security import generate_slug

async def sync_stock(product_id: int, cur=None):
    sql = """
        UPDATE products 
        SET stock = (SELECT COUNT(id) FROM product_items WHERE product_id = %s AND status = 'available') 
        WHERE id = %s
    """
    if cur is not None:
        await cur.execute(sql, (product_id, product_id))
    else:
        await execute(sql, (product_id, product_id))

async def get_public_products(query: Dict[str, Any]) -> Dict[str, Any]:
    page = int(query.get("page", 1) or 1)
    limit = int(query.get("limit", 12) or 12)
    search = query.get("search")
    category = query.get("category")
    sort = "ASC" if str(query.get("sort", "")).upper() == "ASC" else "DESC"
    offset = (page - 1) * limit

    sql = """
        SELECT product_code, category, name, slug, description, price, stock, delivery_type, thumbnail 
        FROM products WHERE status = 'active'
    """
    params = []

    if category:
        sql += " AND category = %s"
        params.append(category)
    if search:
        sql += " AND name LIKE %s"
        params.append(f"%{search}%")

    sql += f" ORDER BY sort_order ASC, created_at {sort} LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    items = await fetch_all(sql, tuple(params))
    for it in items:
        it["price"] = float(it["price"])
        it["stock"] = int(it["stock"])

    count_sql = "SELECT COUNT(id) as total FROM products WHERE status = 'active'"
    count_params = []
    if category:
        count_sql += " AND category = %s"
        count_params.append(category)
    if search:
        count_sql += " AND name LIKE %s"
        count_params.append(f"%{search}%")

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

async def get_product_by_code(product_code: str) -> Dict[str, Any]:
    product = await fetch_one(
        """
        SELECT product_code, category, name, slug, description, price, stock, delivery_type, thumbnail 
        FROM products WHERE product_code = %s AND status = 'active'
        """,
        (product_code,),
    )
    if not product:
        raise ValueError("Sản phẩm không tồn tại hoặc đã bị ẩn")
    res = dict(product)
    res["price"] = float(res["price"])
    res["stock"] = int(res["stock"])
    return res

async def create_product(data: Dict[str, Any]) -> int:
    slug = generate_slug(data.get("name", ""))
    prod_id = await execute(
        """
        INSERT INTO products (product_code, category, name, slug, description, price, delivery_type, thumbnail) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            data["product_code"],
            data.get("category"),
            data["name"],
            slug,
            data.get("description"),
            float(data.get("price", 0)),
            data.get("delivery_type", "manual"),
            data.get("thumbnail"),
        ),
    )
    return prod_id

async def update_product(prod_id: int, data: Dict[str, Any]):
    slug = generate_slug(data["name"]) if "name" in data and data["name"] else None
    fields = ["product_code", "category", "name", "description", "price", "delivery_type", "status", "thumbnail", "sort_order"]
    updates = []
    params = []

    for f in fields:
        if f in data:
            updates.append(f"{f} = %s")
            params.append(data[f])

    if slug:
        updates.append("slug = %s")
        params.append(slug)

    if not updates:
        return

    params.append(prod_id)
    sql = f"UPDATE products SET {', '.join(updates)} WHERE id = %s"
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, tuple(params))
            if cur.rowcount == 0:
                raise ValueError("Sản phẩm không tồn tại")

async def delete_product(prod_id: int):
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE products SET status = 'disabled' WHERE id = %s", (prod_id,))
            if cur.rowcount == 0:
                raise ValueError("Sản phẩm không tồn tại")

async def import_product_items(product_id: int, content_array: List[str]) -> Dict[str, Any]:
    items = [c.strip() for c in content_array if c and c.strip()]
    items = list(dict.fromkeys(items))

    if not items:
        raise ValueError("Không có dữ liệu hợp lệ để import")

    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT id FROM products WHERE id = %s FOR UPDATE", (product_id,))
                prod = await cur.fetchone()
                if not prod:
                    raise ValueError("Sản phẩm không tồn tại")

                await cur.execute("SELECT content FROM product_items WHERE product_id = %s", (product_id,))
                existing = await cur.fetchall()
                existing_set = {e["content"] for e in existing}

                to_insert = [it for it in items if it not in existing_set]
                duplicate_count = len(items) - len(to_insert)

                if to_insert:
                    values = [(product_id, it, it[:30], "available") for it in to_insert]
                    await cur.executemany(
                        "INSERT INTO product_items (product_id, content, identifier, status) VALUES (%s, %s, %s, %s)",
                        values,
                    )

                await sync_stock(product_id, cur)
                await conn.commit()
                return {"inserted": len(to_insert), "duplicate": duplicate_count}
            except Exception:
                await conn.rollback()
                raise

async def update_product_item(item_id: int, content: str):
    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT product_id FROM product_items WHERE id = %s FOR UPDATE", (item_id,))
                row = await cur.fetchone()
                if not row:
                    raise ValueError("Item không tồn tại")

                identifier = content[:30]
                await cur.execute(
                    "UPDATE product_items SET content = %s, identifier = %s WHERE id = %s",
                    (content, identifier, item_id),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def delete_product_item(item_id: int):
    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute("SELECT product_id FROM product_items WHERE id = %s FOR UPDATE", (item_id,))
                row = await cur.fetchone()
                if not row:
                    raise ValueError("Item không tồn tại")

                product_id = row["product_id"]
                await cur.execute("UPDATE product_items SET status = 'deleted' WHERE id = %s", (item_id,))
                await sync_stock(product_id, cur)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def get_admin_product_items(product_id: int, query: Dict[str, Any]) -> Dict[str, Any]:
    page = int(query.get("page", 1) or 1)
    limit = int(query.get("limit", 20) or 20)
    status = query.get("status")
    search = query.get("search")
    offset = (page - 1) * limit

    sql = """
        SELECT id, identifier, content, status, order_id, created_at, sold_at 
        FROM product_items WHERE product_id = %s
    """
    params = [product_id]

    if status:
        sql += " AND status = %s"
        params.append(status)
    if search:
        sql += " AND (identifier LIKE %s OR content LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    items = await fetch_all(sql, tuple(params))
    for it in items:
        if it.get("created_at") and hasattr(it["created_at"], "isoformat"):
            it["created_at"] = it["created_at"].isoformat()
        if it.get("sold_at") and hasattr(it["sold_at"], "isoformat"):
            it["sold_at"] = it["sold_at"].isoformat()

    count_sql = "SELECT COUNT(id) as total FROM product_items WHERE product_id = %s"
    count_params = [product_id]
    if status:
        count_sql += " AND status = %s"
        count_params.append(status)
    if search:
        count_sql += " AND (identifier LIKE %s OR content LIKE %s)"
        count_params.extend([f"%{search}%", f"%{search}%"])

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
