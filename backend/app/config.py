from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_FILE = REPOSITORY_ROOT / ".env"


def _parse_cors_origins(value: Any) -> Any:
    if isinstance(value, str):
        return tuple(origin.strip() for origin in value.split(",") if origin.strip())
    return value


CorsOrigins = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_parse_cors_origins)]


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
    celery_broker_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_result_backend: SecretStr = SecretStr("redis://localhost:6379/1")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    enable_chaos_demo: bool = False
    cors_origins: CorsOrigins = Field(default=("http://localhost:5173", "http://127.0.0.1:5173"))


settings = Settings()
