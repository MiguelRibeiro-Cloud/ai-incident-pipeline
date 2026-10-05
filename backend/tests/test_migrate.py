from pathlib import Path
from unittest.mock import patch

from alembic.config import Config

from app import migrate


def test_migration_config_paths_are_anchored_to_backend() -> None:
    backend_root = Path(migrate.__file__).resolve().parents[1]

    assert migrate.ALEMBIC_CONFIG_PATH == backend_root / "alembic.ini"

    config = Config(str(migrate.ALEMBIC_CONFIG_PATH))
    assert Path(config.get_main_option("script_location")) == backend_root / "migrations"


def test_main_upgrades_to_head_independent_of_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with (
        patch.object(migrate, "Config") as config_class,
        patch.object(migrate.command, "upgrade") as upgrade,
    ):
        migrate.main()

    config_class.assert_called_once_with(str(migrate.ALEMBIC_CONFIG_PATH))
    upgrade.assert_called_once_with(config_class.return_value, "head")
