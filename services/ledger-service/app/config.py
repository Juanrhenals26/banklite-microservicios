from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion del servicio. Todo se puede sobreescribir por variables de entorno."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ledger-service"
    api_port: int = 8003

    database_url: str = (
        "postgresql+psycopg2://banklite:banklite@ledger-db:5432/ledger_db"
    )

    account_service_url: str = "http://account-service:8002"
    account_timeout_seconds: float = 5.0


settings = Settings()
