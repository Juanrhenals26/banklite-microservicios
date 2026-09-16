from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "account-service"
    api_port: int = 8002

    database_url: str = (
        "postgresql+psycopg2://banklite:banklite@account-db:5432/account_db"
    )

    identity_service_url: str = "http://identity-service:8001"
    identity_timeout_seconds: float = 5.0

    rabbitmq_url: str = "amqp://banklite:banklite@rabbitmq:5672/"
    events_exchange: str = "banklite.events"
    events_queue: str = "account.identity-verified"
    enable_consumer: bool = True


settings = Settings()
