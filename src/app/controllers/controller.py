from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from redis import asyncio as aioredis

from src.app.config.config import get_session, get_redis_client
from src.app.exceptions import AccountNotFoundError
from src.app.schemas.schema import CreateAccount, CreateTransaction
from src.app.services.service import AccountService, TransactionService

router = APIRouter(
    prefix="/api",
    tags=["transactions"]
)

# Controllers stay thin: they call the (async) service and let domain exceptions
# propagate to the exception handlers registered in main.py (which log them,
# increment bank_errors_total, and return the right status code). Each handler
# injects the shared async DB session and Redis client and hands them to the
# service.

@router.post("/account", status_code=201)
async def create_account(
    request: CreateAccount,
    session: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis_client),
):
    service = AccountService(session, redis)
    return await service.create_account(request)

@router.get("/account")
async def get_account_by_id(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis_client),
):
    service = AccountService(session, redis)
    account = await service.get_account_by_id(account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")
    return account

@router.get("/transaction/")
async def get_transaction_by_id(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis_client),
):
    service = TransactionService(session, redis)
    return await service.get_transaction_by_account_id(account_id)

@router.post("/transaction/")
async def create_transaction(
    request: CreateTransaction,
    session: AsyncSession = Depends(get_session),
    redis: aioredis.Redis = Depends(get_redis_client),
):
    service = TransactionService(session, redis)
    return await service.create_transaction(request)
