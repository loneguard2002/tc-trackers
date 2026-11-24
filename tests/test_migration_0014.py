from datetime import date

from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def test_the_table_defaults_and_index(db, user_factory, tracker_factory):
    tracker = tracker_factory()
    db.execute(
        text("INSERT INTO target_changes (tracker_id, new_date) VALUES (:t, :d)"),
        {"t": tracker.id, "d": date(2026, 12, 18)},
    )
    reason, old, has_time, by = db.execute(
        text("SELECT reason, old_date, changed_at IS NOT NULL, changed_by FROM target_changes")
    ).one()
    assert (reason, old, has_time, by) == ("", None, True, None)
    names = db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'target_changes'")).scalars().all()
    assert "ix_target_changes_tracker_id_id" in names
    db.rollback()


def test_the_changes_go_with_the_tracker_and_survive_the_person(db, user_factory, tracker_factory):
    user, tracker = user_factory(), tracker_factory()
    db.execute(
        text("INSERT INTO target_changes (tracker_id, changed_by, new_date) VALUES (:t, :u, '2026-12-18')"),
        {"t": tracker.id, "u": user.id},
    )
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
    assert db.execute(text("SELECT count(*), max(changed_by) FROM target_changes")).one() == (1, None)
    db.execute(text("DELETE FROM trackers WHERE id = :t"), {"t": tracker.id})
    assert db.execute(text("SELECT count(*) FROM target_changes")).scalar_one() == 0
    db.rollback()


def test_downgrade_drops_the_table(db):
    try:
        command.downgrade(alembic_config(), "0013")
        assert db.execute(text("SELECT to_regclass('target_changes')")).scalar_one() is None
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
