import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_deleted_rows_free_their_email(db, user_factory):
    user_factory(email="shared@example.com", status="deleted")
    user_factory(email="shared@example.com")  # a live row may reuse the address of a deleted one
    with pytest.raises(IntegrityError):  # but a second live row may not
        user_factory(email="shared@example.com")


def test_downgrade_restores_unique_emails(db, user_factory):
    deleted = user_factory(email="shared@example.com", status="deleted")
    live = user_factory(email="shared@example.com")
    try:
        command.downgrade(alembic_config(), "0009")
        rows = db.execute(text("SELECT id, email, status FROM users ORDER BY id")).all()
        assert rows == [
            (deleted.id, f"shared@example.com#deleted-{deleted.id}", "disabled"),
            (live.id, "shared@example.com", "active"),
        ]
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
