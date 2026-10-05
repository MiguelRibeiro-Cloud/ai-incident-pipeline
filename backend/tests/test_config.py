from pathlib import Path

import pytest

from app.api import jobs
from app.config import PROJECT_ENV_FILE, Settings, settings
from app.services import llm
from app.tasks import process_incident

CONFIG_ENV_KEYS = (
    "DATABASE_URL",
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


def test_api_worker_and_gemini_use_the_same_settings_instance() -> None:
    assert jobs.settings is settings
    assert process_incident.settings is settings
    assert llm.settings is settings


def test_secret_values_are_redacted_from_settings_repr(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=do-not-display-this-key\n"
        "DATABASE_URL=postgresql+psycopg://user:do-not-display-this-password@db/app\n"
    )

    rendered = repr(Settings(_env_file=env_file))

    assert "do-not-display-this-key" not in rendered
    assert "do-not-display-this-password" not in rendered
    assert "**********" in rendered
