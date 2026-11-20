from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from alembic import command
from app.db.session import engine


def _current() -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_migrations_round_trip_and_match_models() -> None:
    cfg = Config("alembic.ini")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert _current() == head

    command.downgrade(cfg, "base")  # every migration must be reversible
    assert _current() is None
    command.upgrade(cfg, "head")
    assert _current() == head
    command.check(cfg)  # models and migrations have not drifted apart
