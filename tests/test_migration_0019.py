from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def _columns(db) -> list[str]:
    query = "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users'"
    return db.execute(text(query)).scalars().all()


def test_downgrade_drops_the_column(db):
    try:
        command.downgrade(alembic_config(), "0018")
        assert "session_version" not in _columns(db) and "is_admin" in _columns(db)
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
