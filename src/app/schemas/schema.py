from pydantic import BaseModel, Field
from datetime import datetime

class CreateTransaction(BaseModel):
    account_id: int = Field(...)
    type: str = Field(...)
    amount: int = Field(...)
    description: str | None = Field(None)
    occured_at: datetime = Field(...)

class CreateAccount(BaseModel):
    balance_paise: int = Field(0, ge=0)
