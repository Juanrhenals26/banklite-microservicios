"""Consumidor ASINCRONO de eventos de RabbitMQ.

Escucha identity.verified y alimenta la proyeccion local verified_users.
Corre en un hilo aparte con su propia conexion, y reintenta si el broker
todavia no esta disponible al arrancar.
"""

import json
import logging
import threading
import time
import uuid

import pika

from .config import settings
from .database import SessionLocal
from .models import VerifiedUser

logger = logging.getLogger(__name__)

EVENT_IDENTITY_VERIFIED = "identity.verified"
_stop = threading.Event()


def _handle_identity_verified(payload: dict) -> None:
    db = SessionLocal()
    try:
        user_id = uuid.UUID(payload["user_id"])
        existing = db.get(VerifiedUser, user_id)
        if existing is None:
            db.add(
                VerifiedUser(
                    user_id=user_id,
                    email=payload["email"],
                    country=payload["country"],
                    verified_at=str(payload.get("verified_at", "")),
                )
            )
        else:
            existing.email = payload["email"]
            existing.country = payload["country"]
            existing.verified_at = str(payload.get("verified_at", ""))
        db.commit()
        logger.info("Proyeccion actualizada por evento identity.verified: %s", user_id)
    finally:
        db.close()


def _on_message(channel, method, properties, body) -> None:
    try:
        payload = json.loads(body.decode("utf-8"))
        _handle_identity_verified(payload)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        logger.exception("Error procesando evento, se descarta sin reencolar")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _consume_forever() -> None:
    while not _stop.is_set():
        try:
            connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
            channel = connection.channel()
            channel.exchange_declare(
                exchange=settings.events_exchange, exchange_type="topic", durable=True
            )
            channel.queue_declare(queue=settings.events_queue, durable=True)
            channel.queue_bind(
                queue=settings.events_queue,
                exchange=settings.events_exchange,
                routing_key=EVENT_IDENTITY_VERIFIED,
            )
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(queue=settings.events_queue, on_message_callback=_on_message)
            logger.info("Escuchando %s en la cola %s", EVENT_IDENTITY_VERIFIED, settings.events_queue)
            channel.start_consuming()
        except Exception as exc:
            logger.warning("Consumidor desconectado (%s). Reintentando en 5s...", exc)
            time.sleep(5)


def start_consumer() -> None:
    if not settings.enable_consumer:
        logger.warning("Consumidor deshabilitado (ENABLE_CONSUMER=false)")
        return
    thread = threading.Thread(target=_consume_forever, name="identity-verified-consumer", daemon=True)
    thread.start()


def stop_consumer() -> None:
    _stop.set()
