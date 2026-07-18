from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from sqlmodel import Session

from src.app.config.config import get_session
from src.app.schemas.schema import CreateTransaction
from src.app.services.service import AccountService, TransactionService

router = APIRouter(
    prefix="/api",
    tags=["transactions"]
)

@router.get("/account")
def get_account_by_id(account_id: int, session: Session = Depends(get_session)):
    service = AccountService(session)
    account = service.get_account_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account

@router.get("/transaction/")
def get_transaction_by_id(account_id: int, session: Session = Depends(get_session)):
    service = TransactionService(session)
    transactions = service.get_transaction_by_account_id(account_id)
    if transactions is None:
        raise HTTPException(status_code=404, detail="Transactions not found")
    return transactions

@router.post("/transaction/")
def create_transaction(request: CreateTransaction, session: Session = Depends(get_session)):
    service = TransactionService(session)
    transaction = service.create_transaction(request)
    return transaction
