"""Consumidor ASINCRONO de eventos de RabbitMQ.

Escucha identity.verified (de identity-service) y transfer.completed (de
transfer-service), y alimenta sus respectivas proyecciones locales
(usuario_verificado, transferencia_recibida). Corre en un hilo aparte con su
propia conexion, y reintenta si el broker todavia no esta disponible al
arrancar.
"""

import json
import logging
import threading
import time
import uuid

import pika

from .config import settings
from .database import SessionLocal
from .models import TransferenciaRecibida, UsuarioVerificado

logger = logging.getLogger(__name__)

EVENT_IDENTITY_VERIFIED = "identity.verified"
EVENT_TRANSFER_COMPLETED = "transfer.completed"
_stop = threading.Event()


def _handle_identity_verified(payload: dict) -> None:
    db = SessionLocal()
    try:
        id_usuario = uuid.UUID(payload["id_usuario"])
        existing = db.get(UsuarioVerificado, id_usuario)
        if existing is None:
            db.add(
                UsuarioVerificado(
                    id_usuario=id_usuario,
                    email=payload["email"],
                    pais_residencia=payload["pais_residencia"],
                    verificado_en=str(payload.get("verificado_en", "")),
                )
            )
        else:
            existing.email = payload["email"]
            existing.pais_residencia = payload["pais_residencia"]
            existing.verificado_en = str(payload.get("verificado_en", ""))
        db.commit()
        logger.info("Proyeccion actualizada por evento identity.verified: %s", id_usuario)
    finally:
        db.close()


def _handle_transfer_completed(payload: dict) -> None:
    db = SessionLocal()
    try:
        id_transferencia = uuid.UUID(payload["id_transferencia"])
        existing = db.get(TransferenciaRecibida, id_transferencia)
        if existing is None:
            db.add(
                TransferenciaRecibida(
                    id_transferencia=id_transferencia,
                    id_cuenta_origen=uuid.UUID(payload["id_cuenta_origen"]),
                    monto=payload["monto"],
                    estado=payload.get("estado", "completada"),
                )
            )
            db.commit()
            logger.info("Proyeccion actualizada por evento transfer.completed: %s", id_transferencia)
    finally:
        db.close()


def _on_message(channel, method, properties, body) -> None:
    try:
        payload = json.loads(body.decode("utf-8"))
        routing_key = method.routing_key
        if routing_key == EVENT_IDENTITY_VERIFIED:
            _handle_identity_verified(payload)
        elif routing_key == EVENT_TRANSFER_COMPLETED:
            _handle_transfer_completed(payload)
        else:
            logger.warning("Evento con routing_key desconocida ignorado: %s", routing_key)
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
            channel.queue_bind(
                queue=settings.events_queue,
                exchange=settings.events_exchange,
                routing_key=EVENT_TRANSFER_COMPLETED,
            )
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(queue=settings.events_queue, on_message_callback=_on_message)
            logger.info(
                "Escuchando %s y %s en la cola %s",
                EVENT_IDENTITY_VERIFIED,
                EVENT_TRANSFER_COMPLETED,
                settings.events_queue,
            )
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
