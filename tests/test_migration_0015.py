from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def test_a_week_note_defaults_to_blank(db, tracker_factory):
    tracker = tracker_factory()
    db.execute(
        text("INSERT INTO weeks (tracker_id, week_ending, target) VALUES (:t, '2026-09-04', 5)"), {"t": tracker.id}
    )
    assert db.execute(text("SELECT note FROM weeks")).scalar_one() == ""
    db.rollback()


def test_downgrade_drops_the_column(db):
    try:
        command.downgrade(alembic_config(), "0014")
        columns = (
            db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'weeks'"))
            .scalars()
            .all()
        )
        assert "note" not in columns
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
