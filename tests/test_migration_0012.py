import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_the_table_has_a_check_on_the_state_and_an_index_on_the_tracker(db, user_factory, tracker_factory):
    user, tracker = user_factory(), tracker_factory()
    db.execute(
        text("INSERT INTO calendar_reminders (user_id, tracker_id, enabled) VALUES (:u, :t, true)"),
        {"u": user.id, "t": tracker.id},
    )
    assert db.execute(text("SELECT sent_state, sequence FROM calendar_reminders")).one() == ("none", 0)
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE calendar_reminders SET sent_state = 'bogus'"))
    db.rollback()
    names = db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'calendar_reminders'")).scalars().all()
    assert "ix_calendar_reminders_tracker_id" in names


def test_downgrade_drops_the_table(db):
    try:
        command.downgrade(alembic_config(), "0011")
        assert db.execute(text("SELECT to_regclass('calendar_reminders')")).scalar_one() is None
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
