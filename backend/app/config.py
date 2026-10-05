from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import urlsplit, urlunsplit

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_FILE = REPOSITORY_ROOT / ".env"


def _parse_cors_origins(value: Any) -> Any:
    if isinstance(value, str):
        return tuple(origin.strip() for origin in value.split(",") if origin.strip())
    return value


CorsOrigins = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_parse_cors_origins)]


def _redis_url_for_database(redis_url: str, database: int) -> str:
    parsed_url = urlsplit(redis_url)
    return urlunsplit(parsed_url._replace(path=f"/{database}"))


class Settings(BaseSettings):
    """Application configuration shared by API, worker, migrations, and services."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://incident_app:incident_app_dev@localhost:5432/incident_pipeline"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379")
    celery_broker_url: SecretStr | None = None
    celery_result_backend: SecretStr | None = None
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    enable_chaos_demo: bool = False
    cors_origins: CorsOrigins = Field(default=("http://localhost:5173", "http://127.0.0.1:5173"))

    @model_validator(mode="after")
    def derive_celery_redis_urls(self) -> Self:
        redis_url = self.redis_url.get_secret_value()
        if self.celery_broker_url is None:
            self.celery_broker_url = SecretStr(_redis_url_for_database(redis_url, 0))
        if self.celery_result_backend is None:
            self.celery_result_backend = SecretStr(_redis_url_for_database(redis_url, 1))
        return self


settings = Settings()
