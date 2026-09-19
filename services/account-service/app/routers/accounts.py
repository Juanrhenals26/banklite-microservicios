import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..identity_client import IdentityUnavailable, get_user
from ..limits import SUPPORTED_COUNTRIES, limits_for
from ..models import Cuenta, LimiteOperativo, RestriccionRegulatoria, TransferenciaRecibida, UsuarioVerificado
from ..schemas import (
    AccountStatusUpdate,
    AccountCreate,
    CuentaCreada,
    CuentaOut,
    LimiteOperativoOut,
    RestriccionRegulatoriaOut,
    TransferenciaRecibidaOut,
    UsuarioVerificadoOut,
)

router = APIRouter(tags=["cuentas"])


def _get_cuenta_or_404(db: Session, id_cuenta: uuid.UUID) -> Cuenta:
    cuenta = db.get(Cuenta, id_cuenta)
    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una cuenta con id {id_cuenta}",
        )
    return cuenta


@router.post("/accounts", response_model=CuentaCreada, status_code=status.HTTP_201_CREATED)
def open_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Abre una cuenta y su modelo normalizado completo (cuenta + limite_operativo
    x2 + restriccion_regulatoria).

    Combina las dos formas de comunicacion:
      - SINCRONA: consulta el usuario a identity-service por REST (GET /users/{id}).
      - ASINCRONA: consulta la proyeccion local usuario_verificado, alimentada
        por el evento identity.verified.
    """
    try:
        usuario = get_user(payload.id_usuario)
    except IdentityUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"identity-service no esta disponible: {exc}",
        )

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El usuario {payload.id_usuario} no existe en identity-service",
        )

    if usuario.get("estado") != "verificado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario no ha completado la verificacion KYC "
                f"(estado actual: {usuario.get('estado')})"
            ),
        )

    pais = str(usuario.get("pais_residencia", "")).upper()
    regulatorio = limits_for(pais)
    if regulatorio is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El pais {pais} no esta habilitado. "
                f"Paises soportados: {', '.join(SUPPORTED_COUNTRIES)}"
            ),
        )

    moneda = payload.moneda or regulatorio["currency"]
    if moneda != regulatorio["currency"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"La moneda {moneda} no corresponde al pais {pais}. "
                f"Moneda regulatoria esperada: {regulatorio['currency']}"
            ),
        )

    proyeccion_encontrada = db.get(UsuarioVerificado, payload.id_usuario) is not None

    cuenta = Cuenta(
        id_usuario=payload.id_usuario,
        moneda=moneda,
        estado="activa",
    )
    db.add(cuenta)
    try:
        db.flush()  # necesita id_cuenta antes de crear limites y restriccion
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario ya tiene una cuenta en {moneda}",
        )

    limite_diario = LimiteOperativo(
        id_cuenta=cuenta.id_cuenta,
        tipo_limite="diario",
        monto_maximo=regulatorio["daily_limit"],
        periodo="dia",
    )
    limite_mensual = LimiteOperativo(
        id_cuenta=cuenta.id_cuenta,
        tipo_limite="mensual",
        monto_maximo=regulatorio["monthly_limit"],
        periodo="mes",
    )
    restriccion = RestriccionRegulatoria(
        id_cuenta=cuenta.id_cuenta,
        pais=pais,
        descripcion=f"Limites regulatorios estandar de {pais} para cuentas en {moneda}",
    )
    db.add_all([limite_diario, limite_mensual, restriccion])
    db.commit()
    db.refresh(cuenta)
    db.refresh(limite_diario)
    db.refresh(limite_mensual)
    db.refresh(restriccion)

    return CuentaCreada(
        cuenta=CuentaOut.model_validate(cuenta),
        limites=[LimiteOperativoOut.model_validate(limite_diario), LimiteOperativoOut.model_validate(limite_mensual)],
        restriccion=RestriccionRegulatoriaOut.model_validate(restriccion),
        validado_via="identity-service (REST sincrono)",
        evento_proyeccion_encontrada=proyeccion_encontrada,
    )


@router.get("/accounts", response_model=list[CuentaOut])
def list_accounts(
    db: Session = Depends(get_db),
    id_usuario: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Cuenta).order_by(Cuenta.fecha_apertura.desc()).limit(limit).offset(offset)
    if id_usuario is not None:
        stmt = stmt.where(Cuenta.id_usuario == id_usuario)
    return db.execute(stmt).scalars().all()


@router.get("/accounts/{id_cuenta}", response_model=CuentaOut)
def get_account(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    return _get_cuenta_or_404(db, id_cuenta)


@router.get("/accounts/{id_cuenta}/limits", response_model=list[LimiteOperativoOut])
def get_account_limits(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    """Tabla limite_operativo de esta cuenta (limite diario y mensual)."""
    _get_cuenta_or_404(db, id_cuenta)
    stmt = select(LimiteOperativo).where(LimiteOperativo.id_cuenta == id_cuenta)
    return db.execute(stmt).scalars().all()


@router.patch("/accounts/{id_cuenta}/status", response_model=CuentaOut)
def update_status(id_cuenta: uuid.UUID, payload: AccountStatusUpdate, db: Session = Depends(get_db)):
    cuenta = _get_cuenta_or_404(db, id_cuenta)
    if cuenta.estado == "cerrada":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Una cuenta cerrada no puede cambiar de estado",
        )
    cuenta.estado = payload.estado
    db.commit()
    db.refresh(cuenta)
    return cuenta


@router.get("/verified-users", response_model=list[UsuarioVerificadoOut], tags=["eventos"])
def list_verified_users(db: Session = Depends(get_db)):
    """Evidencia de la comunicacion ASINCRONA: esta tabla (usuario_verificado)
    solo se llena consumiendo el evento identity.verified desde RabbitMQ."""
    stmt = select(UsuarioVerificado).order_by(UsuarioVerificado.recibido_en.desc())
    return db.execute(stmt).scalars().all()


@router.get(
    "/transfers-received", response_model=list[TransferenciaRecibidaOut], tags=["eventos"]
)
def list_transfers_received(db: Session = Depends(get_db)):
    """Evidencia de la comunicacion ASINCRONA con transfer-service: esta
    tabla (transferencia_recibida) solo se llena consumiendo el evento
    transfer.completed desde RabbitMQ."""
    stmt = select(TransferenciaRecibida).order_by(TransferenciaRecibida.recibido_en.desc())
    return db.execute(stmt).scalars().all()
