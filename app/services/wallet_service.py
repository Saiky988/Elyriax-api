import json
import math
import re
from typing import Any, Dict, Optional
import jwt
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one, get_connection
from app.core.security import generate_transaction_code

async def get_or_create_wallet(user_id: int) -> Dict[str, Any]:
    wallet = await fetch_one("SELECT * FROM wallets WHERE user_id = %s", (user_id,))
    if wallet:
        res = dict(wallet)
        res["balance"] = float(res.get("balance") or 0)
        res["total_deposit"] = float(res.get("total_deposit") or 0)
        res["total_spent"] = float(res.get("total_spent") or 0)
        return res

    wallet_id = await execute("INSERT INTO wallets (user_id) VALUES (%s)", (user_id,))
    new_wallet = await fetch_one("SELECT * FROM wallets WHERE id = %s", (wallet_id,))
    res = dict(new_wallet)
    res["balance"] = float(res.get("balance") or 0)
    res["total_deposit"] = float(res.get("total_deposit") or 0)
    res["total_spent"] = float(res.get("total_spent") or 0)
    return res

async def create_deposit_info(user_id: int, amount: Any) -> Dict[str, Any]:
    try:
        amt = float(amount)
    except (ValueError, TypeError):
        raise ValueError("Số tiền nạp không hợp lệ")

    if amt < 10000:
        raise ValueError("Số tiền nạp tối thiểu là 10,000 VND")

    wallet = await get_or_create_wallet(user_id)
    tx_code = generate_transaction_code()

    await execute(
        """
        INSERT INTO transactions 
        (transaction_code, user_id, wallet_id, type, amount, status, description) 
        VALUES (%s, %s, %s, 'deposit', %s, 'pending', 'Nạp tiền vào ví ELYRIAX')
        """,
        (tx_code, user_id, wallet["id"], amt),
    )

    tx = await fetch_one("SELECT * FROM transactions WHERE transaction_code = %s", (tx_code,))
    res_tx = dict(tx)
    res_tx["amount"] = float(res_tx["amount"])
    if res_tx.get("created_at") and hasattr(res_tx["created_at"], "isoformat"):
        res_tx["created_at"] = res_tx["created_at"].isoformat()

    token_payload = {
        "amount": amt,
        "content": tx_code,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }
    token = jwt.encode(token_payload, settings.JWT_SECRET, algorithm="HS256")
    base_url = settings.BASE_URL or "https://apis.elyriax.com"

    return {
        "transaction": res_tx,
        "payment": {
            "bank": settings.BANK_ID or "MB",
            "account_number": settings.BANK_ACCOUNT_NO,
            "account_name": settings.BANK_ACCOUNT_NAME,
            "amount": amt,
            "content": tx_code,
            "qr_image": f"{base_url}/v1/payment/qr?token={token}",
        },
    }

async def process_sepay_webhook(payload: Dict[str, Any]):
    if payload.get("transferType") != "in":
        return

    content = payload.get("content") or ""
    match = re.search(r"ELYRIAX [A-Z0-9]{6}", content)
    if not match:
        return

    tx_code = match.group(0)
    transfer_amount = float(payload.get("transferAmount") or 0)

    async with get_connection() as conn:
        await conn.begin()
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "SELECT * FROM transactions WHERE transaction_code = %s FOR UPDATE",
                    (tx_code,),
                )
                tx = await cur.fetchone()
                if not tx:
                    await conn.rollback()
                    return

                if tx["status"] != "pending":
                    await conn.rollback()
                    return

                await cur.execute("SELECT * FROM wallets WHERE id = %s FOR UPDATE", (tx["wallet_id"],))
                wallet = await cur.fetchone()
                if not wallet:
                    await conn.rollback()
                    return

                balance_before = float(wallet["balance"])
                expected_amount = float(tx["amount"])

                if transfer_amount >= expected_amount:
                    balance_after = balance_before + expected_amount
                    await cur.execute(
                        "UPDATE wallets SET balance = %s, total_deposit = total_deposit + %s WHERE id = %s",
                        (balance_after, expected_amount, wallet["id"]),
                    )
                    await cur.execute(
                        """
                        UPDATE transactions 
                        SET status = 'completed', balance_before = %s, balance_after = %s, 
                            completed_at = CURRENT_TIMESTAMP, reference_id = %s, metadata = %s 
                        WHERE id = %s
                        """,
                        (balance_before, balance_after, payload.get("referenceCode"), json.dumps(payload), tx["id"]),
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE transactions 
                        SET status = 'failed', completed_at = CURRENT_TIMESTAMP, reference_id = %s, metadata = %s, description = %s 
                        WHERE id = %s
                        """,
                        (payload.get("referenceCode"), json.dumps(payload), "Chuyển khoản không đủ số tiền yêu cầu", tx["id"]),
                    )

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def get_transactions(user_id: int, query: Dict[str, Any]) -> Dict[str, Any]:
    page = int(query.get("page", 1) or 1)
    limit = int(query.get("limit", 10) or 10)
    tx_type = query.get("type")
    status = query.get("status")
    sort = "ASC" if str(query.get("sort", "")).upper() == "ASC" else "DESC"
    offset = (page - 1) * limit

    sql = "SELECT * FROM transactions WHERE user_id = %s"
    params = [user_id]

    if tx_type:
        sql += " AND type = %s"
        params.append(tx_type)
    if status:
        sql += " AND status = %s"
        params.append(status)

    sql += f" ORDER BY created_at {sort} LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = await fetch_all(sql, tuple(params))
    for r in rows:
        r["amount"] = float(r["amount"])
        if r.get("balance_before") is not None:
            r["balance_before"] = float(r["balance_before"])
        if r.get("balance_after") is not None:
            r["balance_after"] = float(r["balance_after"])
        if r.get("created_at") and hasattr(r["created_at"], "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("completed_at") and hasattr(r["completed_at"], "isoformat"):
            r["completed_at"] = r["completed_at"].isoformat()

    count_sql = "SELECT COUNT(id) as total FROM transactions WHERE user_id = %s"
    count_params = [user_id]
    if tx_type:
        count_sql += " AND type = %s"
        count_params.append(tx_type)
    if status:
        count_sql += " AND status = %s"
        count_params.append(status)

    count_row = await fetch_one(count_sql, tuple(count_params))
    total = count_row["total"] if count_row else 0

    return {
        "items": rows,
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": math.ceil(total / limit) if limit > 0 else 1,
        },
    }
