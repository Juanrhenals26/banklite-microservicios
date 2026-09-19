"""Cliente REST SINCRONO hacia account-service.

Antes de registrar el primer asiento contable de una cuenta, ledger-service
confirma de forma sincrona que esa cuenta existe y esta activa en
account-service — ledger no confia a ciegas en el id_cuenta que le pasa quien
lo llama (transfer-service, u otro microservicio en el futuro).
"""

import logging
import uuid

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class AccountUnavailable(RuntimeError):
    """account-service no respondio. Se traduce a un 503 hacia el cliente."""


def get_account(id_cuenta: uuid.UUID) -> dict | None:
    url = f"{settings.account_service_url}/accounts/{id_cuenta}"
    try:
        response = httpx.get(url, timeout=settings.account_timeout_seconds)
    except httpx.RequestError as exc:
        logger.error("Fallo la llamada sincrona a account-service: %s", exc)
        raise AccountUnavailable(str(exc)) from exc

    if response.status_code == 404:
        return None
    if response.status_code >= 500:
        raise AccountUnavailable(f"account-service respondio {response.status_code}")
    response.raise_for_status()
    return response.json()
