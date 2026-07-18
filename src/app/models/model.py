from sqlmodel import Field, SQLModel
import uuid
from datetime import datetime

class Account(SQLModel, table=True):
    id: int = Field(primary_key=True)
    balance_paise: int = Field(default=0, nullable=False)

class Transaction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: int = Field(foreign_key="account.id")
    type: str = Field(nullable=False)
    amount_paise: int = Field(nullable=False)
    description: str | None = Field(nullable=True)
    created_at: datetime = Field(default_factory=datetime.now)
    occured_at: datetime = Field(nullable=False)
