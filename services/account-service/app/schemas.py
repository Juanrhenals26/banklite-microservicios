import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    user_id: uuid.UUID
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Opcional. Si se omite se usa la moneda regulatoria del pais del usuario.",
    )

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.isalpha():
            raise ValueError("currency debe ser un codigo ISO de 3 letras, por ejemplo COP")
        return v.upper()


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    currency: str
    country: str
    daily_limit: Decimal
    monthly_limit: Decimal
    created_at: datetime


class AccountCreated(BaseModel):
    account: AccountOut
    validated_via: str
    event_projection_hit: bool


class AccountStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"active", "suspended", "closed"}
        if v not in allowed:
            raise ValueError(f"status debe ser uno de: {', '.join(sorted(allowed))}")
        return v


class VerifiedUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    country: str
    verified_at: str
    received_at: datetime
