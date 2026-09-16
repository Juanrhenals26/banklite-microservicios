import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..identity_client import IdentityUnavailable, get_user
from ..limits import SUPPORTED_COUNTRIES, limits_for
from ..models import Account, VerifiedUser
from ..schemas import (
    AccountCreate,
    AccountCreated,
    AccountOut,
    AccountStatusUpdate,
    VerifiedUserOut,
)

router = APIRouter(tags=["accounts"])


@router.post("/accounts", response_model=AccountCreated, status_code=status.HTTP_201_CREATED)
def open_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Abre una cuenta.

    Combina las dos formas de comunicacion:
      - SINCRONA: consulta el usuario a identity-service por REST.
      - ASINCRONA: consulta la proyeccion local alimentada por identity.verified.
    """
    try:
        user = get_user(payload.user_id)
    except IdentityUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"identity-service no esta disponible: {exc}",
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El usuario {payload.user_id} no existe en identity-service",
        )

    if user.get("status") != "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario no ha completado la verificacion KYC "
                f"(estado actual: {user.get('status')})"
            ),
        )

    country = str(user.get("country", "")).upper()
    regulatory = limits_for(country)
    if regulatory is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El pais {country} no esta habilitado. "
                f"Paises soportados: {', '.join(SUPPORTED_COUNTRIES)}"
            ),
        )

    currency = payload.currency or regulatory["currency"]
    if currency != regulatory["currency"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"La moneda {currency} no corresponde al pais {country}. "
                f"Moneda regulatoria esperada: {regulatory['currency']}"
            ),
        )

    projection_hit = db.get(VerifiedUser, payload.user_id) is not None

    account = Account(
        user_id=payload.user_id,
        status="active",
        currency=currency,
        country=country,
        daily_limit=regulatory["daily_limit"],
        monthly_limit=regulatory["monthly_limit"],
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario ya tiene una cuenta en {currency}",
        )
    db.refresh(account)

    return AccountCreated(
        account=AccountOut.model_validate(account),
        validated_via="identity-service (REST sincrono)",
        event_projection_hit=projection_hit,
    )


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Account).order_by(Account.created_at.desc()).limit(limit).offset(offset)
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
    return db.execute(stmt).scalars().all()


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una cuenta con id {account_id}",
        )
    return account


@router.patch("/accounts/{account_id}/status", response_model=AccountOut)
def update_status(
    account_id: uuid.UUID, payload: AccountStatusUpdate, db: Session = Depends(get_db)
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una cuenta con id {account_id}",
        )
    if account.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Una cuenta cerrada no puede cambiar de estado",
        )
    account.status = payload.status
    db.commit()
    db.refresh(account)
    return account


@router.get("/verified-users", response_model=list[VerifiedUserOut], tags=["eventos"])
def list_verified_users(db: Session = Depends(get_db)):
    """Evidencia de la comunicacion ASINCRONA: esta tabla solo se llena
    consumiendo el evento identity.verified desde RabbitMQ."""
    stmt = select(VerifiedUser).order_by(VerifiedUser.received_at.desc())
    return db.execute(stmt).scalars().all()
