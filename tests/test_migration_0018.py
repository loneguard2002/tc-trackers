from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def _tables(db) -> list[str]:
    return (
        db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        .scalars()
        .all()
    )


def test_downgrade_drops_the_table(db):
    try:
        command.downgrade(alembic_config(), "0017")
        assert "export_requests" not in _tables(db) and "login_failures" in _tables(db)
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
