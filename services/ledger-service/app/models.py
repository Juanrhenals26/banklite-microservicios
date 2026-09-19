import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Transaccion(Base):
    """Tabla transaccion — cabecera de un movimiento contable.

    Coincide con el modelo oficial: TRANSACCION(id_transaccion, tipo_transaccion,
    referencia, fecha_hora, estado).
    """

    __tablename__ = "transaccion"
    __table_args__ = (Index("idx_transaccion_referencia", "referencia"),)

    id_transaccion: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tipo_transaccion: Mapped[str] = mapped_column(String(32), nullable=False)
    referencia: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    estado: Mapped[str] = mapped_column(String(32), nullable=False)

    asientos: Mapped[list["AsientoContable"]] = relationship(
        back_populates="transaccion", cascade="all, delete-orphan"
    )


class AsientoContable(Base):
    """Tabla asiento_contable — registro de solo inserción (append-only) de
    doble partida. Nunca se modifica ni se borra un asiento ya creado.

    ASIENTO_CONTABLE(id_asiento, id_transaccion FK, id_cuenta_contable FK,
    tipo_movimiento, monto, fecha_registro). Relacion: Transaccion 1:N
    Asiento_Contable, Cuenta_Contable 1:N Asiento_Contable (N:1 desde el asiento).
    """

    __tablename__ = "asiento_contable"
    __table_args__ = (
        CheckConstraint("tipo_movimiento IN ('debito','credito')", name="ck_asiento_tipo_movimiento"),
        CheckConstraint("monto > 0", name="ck_asiento_monto_positivo"),
        Index("idx_asiento_transaccion", "id_transaccion"),
        Index("idx_asiento_cuenta_contable", "id_cuenta_contable"),
    )

    id_asiento: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_transaccion: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transaccion.id_transaccion", ondelete="CASCADE"), nullable=False
    )
    id_cuenta_contable: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cuenta_contable.id_cuenta_contable", ondelete="CASCADE"), nullable=False
    )
    tipo_movimiento: Mapped[str] = mapped_column(String(16), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transaccion: Mapped["Transaccion"] = relationship(back_populates="asientos")
    cuenta_contable: Mapped["CuentaContable"] = relationship(back_populates="asientos")


class CuentaContable(Base):
    """Tabla cuenta_contable — proyección contable de una cuenta bancaria y
    fuente de verdad del saldo. id_cuenta es una referencia LOGICA a la tabla
    cuenta de account-service (otra base de datos, otro microservicio): no
    existe una foreign key real de PostgreSQL entre las dos bases.

    CUENTA_CONTABLE(id_cuenta_contable, id_cuenta FK Ext, saldo_actual, moneda,
    fecha_actualizacion). Una cuenta bancaria tiene exactamente una
    cuenta_contable (por eso id_cuenta es unico aqui).
    """

    __tablename__ = "cuenta_contable"

    id_cuenta_contable: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_cuenta: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
    saldo_actual: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    fecha_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    asientos: Mapped[list["AsientoContable"]] = relationship(back_populates="cuenta_contable")
