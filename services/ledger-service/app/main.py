import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import Base, engine
from .routers import ledger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("%s iniciado", settings.service_name)
    yield


app = FastAPI(
    title="BankLite - Ledger Service",
    description=(
        "Microservicio de contabilidad. Registra todos los movimientos mediante "
        "el principio de doble partida y es la fuente de verdad del saldo de "
        "cada cuenta. Valida sincronamente contra account-service."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # solo para desarrollo local; en produccion se restringe al dominio del panel
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ledger.router)


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
