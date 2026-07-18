from sqlmodel import Session, select

from src.app.models.model import Account, Transaction
from src.app.schemas.schema import CreateTransaction

class TransactionService:

    def __init__(self, session: Session):
        self.session = session

    def create_transaction(self, transaction: CreateTransaction):
        account = self.session.get(Account, transaction.account_id)
        if not account:
            raise ValueError("Account not found")

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
        return new_transaction

    def get_transaction_by_account_id(self, account_id: int):
        account = self.session.get(Account, account_id)
        if not account:
            raise ValueError("Account not found")

        statement = select(Transaction).where(Transaction.account_id == account_id)
        result = self.session.exec(statement).all()
        return result

class AccountService:
    def __init__(self, session: Session):
        self.session = session

    def get_account_by_id(self, account_id: int):
        return self.session.get(Account, account_id)
