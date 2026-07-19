import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from src.app.exceptions import AccountNotFoundError, DatabaseError
from src.app.models.model import Account, Transaction
from src.app.observability.metrics import TRANSACTIONS_CREATED, TRANSACTION_AMOUNT_PAISE
from src.app.schemas.schema import CreateAccount, CreateTransaction

log = logging.getLogger(__name__)


class TransactionService:

    def __init__(self, session: Session):
        self.session = session

    def create_transaction(self, transaction: CreateTransaction):
        try:
            account = self.session.get(Account, transaction.account_id)
            if not account:
                log.warning("create_transaction: account %s not found", transaction.account_id)
                raise AccountNotFoundError(f"Account {transaction.account_id} not found")

            new_transaction = Transaction(
                account_id=transaction.account_id,
                type=transaction.type,
                amount_paise=transaction.amount,
                description=transaction.description,
                occured_at=transaction.occured_at
            )

            delta = transaction.amount if transaction.type == "credit" else -transaction.amount
            account.balance_paise += delta

            self.session.add(new_transaction)
            self.session.add(account)
            self.session.commit()
            self.session.refresh(new_transaction)
        except AccountNotFoundError:
            # Domain error — already logged; let it propagate to the handler.
            raise
        except SQLAlchemyError as e:
            self.session.rollback()
            log.exception("create_transaction: database error for account %s", transaction.account_id)
            raise DatabaseError("Failed to create transaction") from e

        # Record business metrics only after a successful commit.
        TRANSACTIONS_CREATED.labels(type=transaction.type).inc()
        TRANSACTION_AMOUNT_PAISE.labels(type=transaction.type).inc(transaction.amount)
        log.info(
            "transaction created: id=%s account=%s type=%s amount=%s",
            new_transaction.id, transaction.account_id, transaction.type, transaction.amount,
        )

        return new_transaction

    def get_transaction_by_account_id(self, account_id: int):
        try:
            account = self.session.get(Account, account_id)
            if not account:
                log.warning("get_transaction: account %s not found", account_id)
                raise AccountNotFoundError(f"Account {account_id} not found")

            statement = select(Transaction).where(Transaction.account_id == account_id)
            return self.session.exec(statement).all()
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as e:
            self.session.rollback()
            log.exception("get_transaction: database error for account %s", account_id)
            raise DatabaseError("Failed to fetch transactions") from e


class AccountService:
    def __init__(self, session: Session):
        self.session = session

    def get_account_by_id(self, account_id: int):
        try:
            return self.session.get(Account, account_id)
        except SQLAlchemyError as e:
            self.session.rollback()
            log.exception("get_account: database error for account %s", account_id)
            raise DatabaseError("Failed to fetch account") from e

    def create_account(self, data: CreateAccount):
        try:
            account = Account(balance_paise=data.balance_paise)
            self.session.add(account)
            self.session.commit()
            self.session.refresh(account)
        except SQLAlchemyError as e:
            self.session.rollback()
            log.exception("create_account: database error")
            raise DatabaseError("Failed to create account") from e

        log.info("account created: id=%s balance=%s", account.id, account.balance_paise)
        return account
