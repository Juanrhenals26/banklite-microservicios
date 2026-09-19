import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MovimientoIn(BaseModel):
    id_cuenta: uuid.UUID
    tipo_movimiento: Literal["debito", "credito"]
    monto: Decimal = Field(gt=0)


class EntryCreate(BaseModel):
    tipo_transaccion: str = Field(min_length=1, max_length=32, examples=["transferencia"])
    referencia: str = Field(min_length=3, max_length=64)
    movimientos: list[MovimientoIn] = Field(min_length=2)

    @field_validator("movimientos")
    @classmethod
    def partida_doble(cls, v: list["MovimientoIn"]) -> list["MovimientoIn"]:
        debitos = sum((m.monto for m in v if m.tipo_movimiento == "debito"), Decimal("0"))
        creditos = sum((m.monto for m in v if m.tipo_movimiento == "credito"), Decimal("0"))
        if debitos != creditos:
            raise ValueError(
                f"la partida doble no balancea: debitos={debitos} creditos={creditos}"
            )
        return v


class AsientoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_asiento: uuid.UUID
    id_transaccion: uuid.UUID
    id_cuenta_contable: uuid.UUID
    tipo_movimiento: str
    monto: Decimal
    fecha_registro: datetime


class TransaccionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_transaccion: uuid.UUID
    tipo_transaccion: str
    referencia: str
    fecha_hora: datetime
    estado: str
    asientos: list[AsientoOut] = []


class CuentaContableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_cuenta_contable: uuid.UUID
    id_cuenta: uuid.UUID
    saldo_actual: Decimal
    moneda: str
    fecha_actualizacion: datetime
