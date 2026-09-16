import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .config import settings
from .consumer import start_consumer, stop_consumer
from .database import Base, engine
from .routers import accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    start_consumer()
    logger.info("%s iniciado", settings.service_name)
    yield
    stop_consumer()


app = FastAPI(
    title="BankLite - Account Service",
    description=(
        "Microservicio de cuentas. Consume el evento identity.verified (asincrono) "
        "y valida al usuario contra identity-service por REST (sincrono) antes de "
        "abrir una cuenta con los limites regulatorios de su pais."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(accounts.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "service": settings.service_name}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servicio"},
    )
