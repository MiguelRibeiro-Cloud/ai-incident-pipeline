from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def main() -> None:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
