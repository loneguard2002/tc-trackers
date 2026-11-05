from alembic import command
from conftest import alembic_config
from sqlalchemy import inspect


def test_upgrade_creates_region_grants_and_downgrade_drops_it(db):
    try:
        command.downgrade(alembic_config(), "0006")
        assert "region_grants" not in inspect(db.connection()).get_table_names()
        db.rollback()
        command.upgrade(alembic_config(), "head")
        columns = {c["name"]: c for c in inspect(db.connection()).get_columns("region_grants")}
        assert set(columns) == {"region_id", "user_id", "role", "created_at"}
        assert not columns["created_at"]["nullable"]
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
