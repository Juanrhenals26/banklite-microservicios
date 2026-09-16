import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Account(Base):
    """Tabla accounts del Account DB:
    (id, user_id, status, currency, daily_limit, monthly_limit)."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "currency", name="uq_account_user_currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    daily_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VerifiedUser(Base):
    """Proyeccion local alimentada por el evento ASINCRONO identity.verified.

    Account Service no consulta la base de datos de Identity: se entera de que un
    usuario quedo verificado porque consume el evento desde RabbitMQ.
    """

    __tablename__ = "verified_users"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    verified_at: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
