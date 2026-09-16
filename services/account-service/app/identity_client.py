"""Cliente REST SINCRONO hacia identity-service.

Toda apertura de cuenta valida contra Identity en tiempo real: el evento
asincrono dice que el usuario fue verificado, pero antes de crear la cuenta se
confirma el estado actual del usuario con una llamada directa.
"""

import logging
import uuid

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class IdentityUnavailable(RuntimeError):
    """identity-service no respondio. Se traduce a un 503 hacia el cliente."""


def get_user(user_id: uuid.UUID) -> dict | None:
    """Devuelve el usuario, o None si Identity responde 404."""
    url = f"{settings.identity_service_url}/users/{user_id}"
    try:
        response = httpx.get(url, timeout=settings.identity_timeout_seconds)
    except httpx.RequestError as exc:
        logger.error("Fallo la llamada sincrona a identity-service: %s", exc)
        raise IdentityUnavailable(str(exc)) from exc

    if response.status_code == 404:
        return None
    if response.status_code >= 500:
        raise IdentityUnavailable(f"identity-service respondio {response.status_code}")
    response.raise_for_status()
    return response.json()
