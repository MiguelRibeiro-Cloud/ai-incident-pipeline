from pathlib import Path

import pytest

from app.api import jobs
from app.config import PROJECT_ENV_FILE, Settings, settings
from app.services import llm
from app.tasks import process_incident

CONFIG_ENV_KEYS = (
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "ENABLE_CHAOS_DEMO",
    "CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def clear_application_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_local_env(path: Path) -> None:
    path.write_text(
        "GEMINI_API_KEY=local-test-key\n"
        "GEMINI_MODEL=local-test-model\n"
        "ENABLE_CHAOS_DEMO=true\n"
        "CORS_ORIGINS=http://localhost:5173,https://demo.example\n"
    )


def test_project_env_path_is_anchored_to_repository_root(tmp_path: Path) -> None:
    expected_root = Path(__file__).resolve().parents[2]

    assert PROJECT_ENV_FILE == expected_root / ".env"

    env_file = tmp_path / ".env"
    _write_local_env(env_file)
    local_settings = Settings(_env_file=env_file)

    assert local_settings.gemini_api_key.get_secret_value() == "local-test-key"
    assert local_settings.gemini_model == "local-test-model"
    assert local_settings.enable_chaos_demo is True
    assert local_settings.cors_origins == (
        "http://localhost:5173",
        "https://demo.example",
    )


def test_process_environment_overrides_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    _write_local_env(env_file)
    monkeypatch.setenv("GEMINI_MODEL", "deployment-model")
    monkeypatch.setenv("ENABLE_CHAOS_DEMO", "false")

    deployment_settings = Settings(_env_file=env_file)

    assert deployment_settings.gemini_model == "deployment-model"
    assert deployment_settings.enable_chaos_demo is False


def test_default_local_redis_url_and_celery_databases() -> None:
    local_settings = Settings(_env_file=None)

    assert local_settings.redis_url.get_secret_value() == "redis://localhost:6379"
    assert local_settings.celery_broker_url.get_secret_value() == "redis://localhost:6379/0"
    assert local_settings.celery_result_backend.get_secret_value() == "redis://localhost:6379/1"


def test_redis_url_derives_broker_database_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6380/7?socket_timeout=5")

    deployment_settings = Settings(_env_file=None)

    assert (
        deployment_settings.celery_broker_url.get_secret_value()
        == "redis://cache.internal:6380/0?socket_timeout=5"
    )


def test_redis_url_derives_result_database_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "rediss://cache.internal:6380/7?ssl_cert_reqs=required")

    deployment_settings = Settings(_env_file=None)

    assert (
        deployment_settings.celery_result_backend.get_secret_value()
        == "rediss://cache.internal:6380/1?ssl_cert_reqs=required"
    )


def test_redis_credentials_and_query_parameters_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "REDIS_URL",
        "rediss://service-user:p%40ssword@cache.example:6380/9?ssl_cert_reqs=required",
    )

    deployment_settings = Settings(_env_file=None)

    assert (
        deployment_settings.celery_broker_url.get_secret_value()
        == "rediss://service-user:p%40ssword@cache.example:6380/0?ssl_cert_reqs=required"
    )
    assert (
        deployment_settings.celery_result_backend.get_secret_value()
        == "rediss://service-user:p%40ssword@cache.example:6380/1?ssl_cert_reqs=required"
    )


def test_railway_style_authenticated_redis_url_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "REDIS_URL",
        "redis://default:railway-password@redis.railway.internal:6379/5",
    )

    deployment_settings = Settings(_env_file=None)

    assert (
        deployment_settings.celery_broker_url.get_secret_value()
        == "redis://default:railway-password@redis.railway.internal:6379/0"
    )
    assert (
        deployment_settings.celery_result_backend.get_secret_value()
        == "redis://default:railway-password@redis.railway.internal:6379/1"
    )


def test_explicit_celery_broker_url_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://shared-cache:6379/8")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://dedicated-broker:6379/4")

    deployment_settings = Settings(_env_file=None)

    assert (
        deployment_settings.celery_broker_url.get_secret_value()
        == "redis://dedicated-broker:6379/4"
    )
    assert (
        deployment_settings.celery_result_backend.get_secret_value()
        == "redis://shared-cache:6379/1"
    )


def test_explicit_celery_result_backend_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://shared-cache:6379/8")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://dedicated-results:6379/6")

    deployment_settings = Settings(_env_file=None)

    assert deployment_settings.celery_broker_url.get_secret_value() == "redis://shared-cache:6379/0"
    assert (
        deployment_settings.celery_result_backend.get_secret_value()
        == "redis://dedicated-results:6379/6"
    )


def test_api_worker_and_gemini_use_the_same_settings_instance() -> None:
    assert jobs.settings is settings
    assert process_incident.settings is settings
    assert llm.settings is settings


def test_secret_values_are_redacted_from_settings_repr(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=do-not-display-this-key\n"
        "DATABASE_URL=postgresql+psycopg://user:do-not-display-this-password@db/app\n"
        "REDIS_URL=redis://default:do-not-display-this-redis-password@cache:6379/5\n"
    )

    rendered = repr(Settings(_env_file=env_file))

    assert "do-not-display-this-key" not in rendered
    assert "do-not-display-this-password" not in rendered
    assert "do-not-display-this-redis-password" not in rendered
    assert "**********" in rendered
