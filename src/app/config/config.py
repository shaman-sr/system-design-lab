import os
from uuid import uuid4

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from redis import asyncio as aioredis

_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:mysecretpassword@db:5432/bank",
)
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

_sep = "&" if "?" in _raw_url else "?"
DATABASE_URL = f"{_raw_url}{_sep}prepared_statement_cache_size=0"

async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)

async_session_pool = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def create_db_and_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session():
    async with async_session_pool() as session:
        yield session

REDIS_URL = os.getenv("REDIS_URL", "redis://:MySecurePassword123@redis:6379/0")
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

async def get_redis_client():
    return redis_client
