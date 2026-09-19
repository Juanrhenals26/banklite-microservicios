import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(timezone.utc).date()


class Cuenta(Base):
    """Tabla cuenta — entidad raiz del microservicio de Cuentas.

    Coincide con el modelo oficial: CUENTA(id_cuenta, id_usuario FK externa,
    tipo_cuenta, moneda, estado, fecha_apertura, fecha_cierre).

    id_usuario es una referencia LOGICA al usuario de identity-service (otra
    base de datos, otro microservicio): no existe una foreign key real de
    PostgreSQL entre las dos bases (database-per-service). El pais del
    titular no se duplica aqui: vive en restriccion_regulatoria, siguiendo
    la normalizacion 3FN que exige el documento.
    """

    __tablename__ = "cuenta"
    __table_args__ = (
        UniqueConstraint("id_usuario", "moneda", name="uq_cuenta_usuario_moneda"),
        CheckConstraint("estado IN ('activa','suspendida','cerrada')", name="ck_cuenta_estado"),
        Index("idx_cuenta_usuario", "id_usuario"),
    )

    id_cuenta: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_usuario: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tipo_cuenta: Mapped[str] = mapped_column(String(32), nullable=False, default="ahorros")
    moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    estado: Mapped[str] = mapped_column(String(16), nullable=False, default="activa")
    fecha_apertura: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    limites: Mapped[list["LimiteOperativo"]] = relationship(
        back_populates="cuenta", cascade="all, delete-orphan"
    )
    restricciones: Mapped[list["RestriccionRegulatoria"]] = relationship(
        back_populates="cuenta", cascade="all, delete-orphan"
    )


class LimiteOperativo(Base):
    """Tabla limite_operativo.

    LIMITE_OPERATIVO(id_limite, id_cuenta FK, tipo_limite, monto_maximo,
    periodo). Relacion: Cuenta 1:N Limite_Operativo (una cuenta tiene un
    limite diario y un limite mensual, cada uno en su propia fila).
    """

    __tablename__ = "limite_operativo"
    __table_args__ = (
        CheckConstraint("monto_maximo >= 0", name="ck_limite_monto_no_negativo"),
        Index("idx_limite_cuenta", "id_cuenta"),
    )

    id_limite: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_cuenta: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cuenta.id_cuenta", ondelete="CASCADE"), nullable=False
    )
    tipo_limite: Mapped[str] = mapped_column(String(16), nullable=False)  # 'diario' | 'mensual'
    monto_maximo: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    periodo: Mapped[str] = mapped_column(String(16), nullable=False)  # 'dia' | 'mes'

    cuenta: Mapped["Cuenta"] = relationship(back_populates="limites")


class RestriccionRegulatoria(Base):
    """Tabla restriccion_regulatoria.

    RESTRICCION_REGULATORIA(id_restriccion, id_cuenta FK, pais,
    descripcion, fecha_aplicacion). Relacion: Cuenta 1:N
    Restriccion_Regulatoria.
    """

    __tablename__ = "restriccion_regulatoria"
    __table_args__ = (Index("idx_restriccion_cuenta", "id_cuenta"),)

    id_restriccion: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_cuenta: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cuenta.id_cuenta", ondelete="CASCADE"), nullable=False
    )
    pais: Mapped[str] = mapped_column(String(2), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=True)
    fecha_aplicacion: Mapped[date] = mapped_column(Date, default=_today)

    cuenta: Mapped["Cuenta"] = relationship(back_populates="restricciones")


class UsuarioVerificado(Base):
    """Proyeccion local ASINCRONA — NO forma parte del modelo entidad-relacion
    formal del documento. Es una tabla propia de la implementacion, exigida
    por el patron de comunicacion asincrona: se alimenta exclusivamente del
    evento identity.verified consumido desde RabbitMQ, sin que account-service
    consulte nunca la base de datos de identity-service.
    """

    __tablename__ = "usuario_verificado"

    id_usuario: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    pais_residencia: Mapped[str] = mapped_column(String(2), nullable=False)
    verificado_en: Mapped[str] = mapped_column(String(64), nullable=False)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TransferenciaRecibida(Base):
    """Proyeccion local ASINCRONA — NO forma parte del modelo entidad-relacion
    formal del documento. Igual que usuario_verificado, es una tabla propia de
    la implementacion que demuestra que account-service tambien reacciona al
    evento transfer.completed publicado por transfer-service, sin llamarlo
    nunca de forma sincrona para saberlo.
    """

    __tablename__ = "transferencia_recibida"

    id_transferencia: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    id_cuenta_origen: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(16), nullable=False)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
