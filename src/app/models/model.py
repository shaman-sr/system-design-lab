from sqlmodel import Field, SQLModel
import uuid
from datetime import datetime
import sqlmodel

class Account(SQLModel, table=True):
    # id is None until the row is inserted; the DB assigns an autoincrement value.
    id: int | None = Field(default=None, primary_key=True)
    balance_paise: int = Field(default=0, nullable=False)

class Transaction(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    type: str = Field(nullable=False)
    amount_paise: int = Field(nullable=False)
    description: str | None = Field(nullable=True)
    created_at: datetime = Field(
        sa_column=sqlmodel.Column(sqlmodel.DateTime(timezone=True), nullable=False)
    )
    occured_at: datetime = Field(
        sa_column=sqlmodel.Column(sqlmodel.DateTime(timezone=True), nullable=False)
    )
