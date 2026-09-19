import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..account_client import AccountUnavailable, get_account
from ..database import get_db
from ..models import AsientoContable, CuentaContable, Transaccion
from ..schemas import CuentaContableOut, EntryCreate, TransaccionOut

router = APIRouter(prefix="/ledger", tags=["ledger"])

# Cuenta contable especial (no pertenece a ningun usuario real): registra el
# dinero que sale hacia rieles externos (ACH/SWIFT), donde el beneficiario no
# tiene una cuenta dentro de BankLite. Es el equivalente simplificado de una
# cuenta nostro/de compensacion en un banco real. No se valida contra
# account-service porque no es una cuenta de cliente.
CUENTA_PUENTE_EXTERNA = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _get_or_create_cuenta_contable(db: Session, id_cuenta: uuid.UUID) -> CuentaContable:
    cuenta_contable = (
        db.execute(select(CuentaContable).where(CuentaContable.id_cuenta == id_cuenta))
        .scalars()
        .first()
    )
    if cuenta_contable is not None:
        return cuenta_contable

    if id_cuenta == CUENTA_PUENTE_EXTERNA:
        cuenta_contable = CuentaContable(id_cuenta=id_cuenta, saldo_actual=0, moneda="COP")
        db.add(cuenta_contable)
        db.flush()
        return cuenta_contable

    try:
        cuenta = get_account(id_cuenta)
    except AccountUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"account-service no esta disponible: {exc}",
        )
    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La cuenta {id_cuenta} no existe en account-service",
        )
    if cuenta.get("estado") != "activa":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La cuenta {id_cuenta} no esta activa (estado: {cuenta.get('estado')})",
        )

    cuenta_contable = CuentaContable(
        id_cuenta=id_cuenta,
        saldo_actual=0,
        moneda=cuenta.get("moneda", "COP"),
    )
    db.add(cuenta_contable)
    db.flush()
    return cuenta_contable


@router.post("/entries", response_model=TransaccionOut, status_code=status.HTTP_201_CREATED)
def create_entry(payload: EntryCreate, db: Session = Depends(get_db)):
    """Registra una transaccion con sus asientos de doble partida (append-only).

    Valida SINCRONAMENTE contra account-service que cada cuenta referenciada
    existe y esta activa (la primera vez que se ve esa cuenta), y actualiza el
    saldo_actual de cada cuenta_contable. Convencion de signo: un 'credito'
    aumenta el saldo del titular, un 'debito' lo disminuye (vista desde el
    cliente, no desde la contabilidad interna del banco).
    """
    transaccion = Transaccion(
        tipo_transaccion=payload.tipo_transaccion,
        referencia=payload.referencia,
        estado="registrada",
    )
    db.add(transaccion)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La referencia {payload.referencia} ya existe",
        )

    asientos = []
    for mov in payload.movimientos:
        cuenta_contable = _get_or_create_cuenta_contable(db, mov.id_cuenta)
        asiento = AsientoContable(
            id_transaccion=transaccion.id_transaccion,
            id_cuenta_contable=cuenta_contable.id_cuenta_contable,
            tipo_movimiento=mov.tipo_movimiento,
            monto=mov.monto,
        )
        db.add(asiento)
        if mov.tipo_movimiento == "debito":
            cuenta_contable.saldo_actual -= mov.monto
        else:
            cuenta_contable.saldo_actual += mov.monto
        cuenta_contable.fecha_actualizacion = datetime.now(timezone.utc)
        asientos.append(asiento)

    db.commit()
    db.refresh(transaccion)
    for asiento in asientos:
        db.refresh(asiento)
    return transaccion


@router.get("/accounts/{id_cuenta}", response_model=CuentaContableOut)
def get_ledger_account(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    """Saldo actual de una cuenta. 404 si todavia no ha tenido ningun
    movimiento (nunca se creo su cuenta_contable)."""
    cuenta_contable = (
        db.execute(select(CuentaContable).where(CuentaContable.id_cuenta == id_cuenta))
        .scalars()
        .first()
    )
    if cuenta_contable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La cuenta {id_cuenta} aun no tiene movimientos registrados en el ledger",
        )
    return cuenta_contable


@router.get("/transactions/{id_transaccion}", response_model=TransaccionOut)
def get_transaction(id_transaccion: uuid.UUID, db: Session = Depends(get_db)):
    transaccion = db.get(Transaccion, id_transaccion)
    if transaccion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una transaccion con id {id_transaccion}",
        )
    return transaccion
