import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_the_table_has_a_check_on_the_kind_defaults_and_an_index(db, user_factory, tracker_factory):
    user, tracker = user_factory(), tracker_factory()
    db.execute(
        text("INSERT INTO calendar_reminder_events (user_id, tracker_id, kind) VALUES (:u, :t, 'sent')"),
        {"u": user.id, "t": tracker.id},
    )
    detail, has_time = db.execute(text("SELECT detail, at IS NOT NULL FROM calendar_reminder_events")).one()
    assert (detail, has_time) == ("", True)
    with pytest.raises(IntegrityError):
        db.execute(
            text("INSERT INTO calendar_reminder_events (user_id, tracker_id, kind) VALUES (:u, :t, 'bogus')"),
            {"u": user.id, "t": tracker.id},
        )
    db.rollback()
    names = (
        db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'calendar_reminder_events'"))
        .scalars()
        .all()
    )
    assert "ix_calendar_reminder_events_user_id_tracker_id_at" in names


def test_the_events_go_with_the_person(db, user_factory, tracker_factory):
    user, tracker = user_factory(), tracker_factory()
    db.execute(
        text("INSERT INTO calendar_reminder_events (user_id, tracker_id, kind) VALUES (:u, :t, 'sent')"),
        {"u": user.id, "t": tracker.id},
    )
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
    assert db.execute(text("SELECT count(*) FROM calendar_reminder_events")).scalar_one() == 0
    db.rollback()


def test_downgrade_drops_the_table(db):
    try:
        command.downgrade(alembic_config(), "0012")
        assert db.execute(text("SELECT to_regclass('calendar_reminder_events')")).scalar_one() is None
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
