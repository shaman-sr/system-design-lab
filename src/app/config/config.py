import os

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# The async engine needs an async driver. docker-compose and the README pass a
# plain "postgresql://" URL (the psycopg2 / sync scheme); normalize it to the
# asyncpg driver so create_async_engine() doesn't reject it.
_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:mysecretpassword@db:5432/bank",
)
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
DATABASE_URL = _raw_url

async_engine = create_async_engine(DATABASE_URL, echo=False)

# class_=AsyncSession must be SQLModel's AsyncSession (not SQLAlchemy's) so the
# services can call session.exec(); SQLAlchemy's AsyncSession only has execute().
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
