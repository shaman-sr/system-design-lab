import os
from uuid import uuid4

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

# We connect through PgBouncer in *transaction* pooling mode (a server connection
# is only borrowed for the duration of each transaction, so many replicas share a
# small pool). That breaks asyncpg's default prepared-statement behaviour: named
# prepared statements outlive a transaction, but the next transaction may land on
# a *different* server connection that never saw them ("prepared statement
# __asyncpg_stmt_x__ does not exist" / "already exists"). Disable both prepared-
# statement caches and give every statement a unique name so nothing is reused
# across pooled connections.
#   - prepared_statement_cache_size=0 : SQLAlchemy asyncpg dialect's own cache
#   - statement_cache_size=0          : asyncpg's internal cache
#   - prepared_statement_name_func    : unique name per statement (SQLAlchemy >=2.0.18)
_sep = "&" if "?" in _raw_url else "?"
DATABASE_URL = f"{_raw_url}{_sep}prepared_statement_cache_size=0"

async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)

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
