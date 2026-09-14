import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple
import aiomysql
from app.core.config import settings

logger = logging.getLogger("Database")

_pool: Optional[aiomysql.Pool] = None

async def init_db_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        try:
            _pool = await aiomysql.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db=settings.DB_NAME,
                minsize=1,
                maxsize=settings.DB_CONNECTION_LIMIT,
                autocommit=True,
                cursorclass=aiomysql.DictCursor,
                charset="utf8mb4",
            )
            logger.info("[DB] MySQL connection pool initialized successfully")
        except Exception as e:
            logger.error(f"[DB] Failed to connect to MySQL: {e}")
            _pool = None
    return _pool

async def close_db_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("[DB] MySQL connection pool closed")

def get_pool() -> Optional[aiomysql.Pool]:
    return _pool

@asynccontextmanager
async def get_connection():
    global _pool
    if _pool is None:
        await init_db_pool()
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    async with _pool.acquire() as conn:
        yield conn

async def fetch_all(sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params or ())
            return await cursor.fetchall()

async def fetch_one(sql: str, params: Optional[Tuple[Any, ...]] = None) -> Optional[Dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params or ())
            return await cursor.fetchone()

async def execute(sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
    async with get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params or ())
            return cursor.lastrowid
