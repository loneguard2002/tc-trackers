from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def test_a_person_can_be_turned_down(db, user_factory):
    user = user_factory(status="declined", auth_source="sso", password_hash=None)
    assert db.execute(text("SELECT status FROM users WHERE id = :id"), {"id": user.id}).scalar_one() == "declined"


def test_downgrade_turns_declined_people_into_disabled_ones(db, user_factory):
    declined = user_factory(status="declined", auth_source="sso", password_hash=None)
    try:
        command.downgrade(alembic_config(), "0010")
        assert (
            db.execute(text("SELECT status FROM users WHERE id = :id"), {"id": declined.id}).scalar_one() == "disabled"
        )
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
