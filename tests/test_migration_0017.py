import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _tables(db) -> list[str]:
    return (
        db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        .scalars()
        .all()
    )


def test_a_failure_takes_the_time_by_default(db):
    db.execute(text("INSERT INTO login_failures (kind, value) VALUES ('account', 'a@example.com')"))
    assert db.execute(text("SELECT at IS NOT NULL FROM login_failures")).scalar_one()
    db.rollback()


def test_the_kind_is_account_or_address(db):
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO login_failures (kind, value) VALUES ('other', 'x')"))
    db.rollback()


def test_downgrade_drops_the_table(db):
    try:
        command.downgrade(alembic_config(), "0016")
        assert "login_failures" not in _tables(db)
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
