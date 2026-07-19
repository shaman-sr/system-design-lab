from fastapi import APIRouter, Depends
from sqlmodel import Session

from src.app.config.config import get_session
from src.app.exceptions import AccountNotFoundError
from src.app.schemas.schema import CreateAccount, CreateTransaction
from src.app.services.service import AccountService, TransactionService

router = APIRouter(
    prefix="/api",
    tags=["transactions"]
)

# Controllers stay thin: they call the service and let domain exceptions
# propagate to the exception handlers registered in main.py (which log them,
# increment bank_errors_total, and return the right status code).

@router.post("/account", status_code=201)
def create_account(request: CreateAccount, session: Session = Depends(get_session)):
    service = AccountService(session)
    return service.create_account(request)

@router.get("/account")
def get_account_by_id(account_id: int, session: Session = Depends(get_session)):
    service = AccountService(session)
    account = service.get_account_by_id(account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")
    return account

@router.get("/transaction/")
def get_transaction_by_id(account_id: int, session: Session = Depends(get_session)):
    service = TransactionService(session)
    return service.get_transaction_by_account_id(account_id)

@router.post("/transaction/")
def create_transaction(request: CreateTransaction, session: Session = Depends(get_session)):
    service = TransactionService(session)
    return service.create_transaction(request)
