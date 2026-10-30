import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import func, select, text

from tracker.auth.roles import visible_trackers
from tracker.models import AuditLog, PermissionSet, Team, User


@pytest.fixture
def at_revision_0002(db):
    command.downgrade(alembic_config(), "0002")
    try:
        yield
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")


def _insert_user(db, email, status="active", is_admin=False) -> int:
    return db.execute(
        text(
            "INSERT INTO users (email, full_name, auth_source, status, is_admin) "
            "VALUES (:e, :e, 'local', :s, :a) RETURNING id"
        ),
        {"e": email, "s": status, "a": is_admin},
    ).scalar_one()


def _insert_tracker(db, name) -> int:
    return db.execute(
        text(
            "INSERT INTO trackers (name, week_ending_weekday, first_week_ending, last_week_ending) "
            "VALUES (:n, 4, '2026-09-04', '2026-12-25') RETURNING id"
        ),
        {"n": name},
    ).scalar_one()


def _insert_audit(db, entity, entity_id) -> int:
    return db.execute(
        text("INSERT INTO audit_log (action, entity, entity_id) VALUES ('x', :e, :i) RETURNING id"),
        {"e": entity, "i": entity_id},
    ).scalar_one()


def test_upgrade_keeps_visible_trackers_and_backfills_affected_users(db, at_revision_0002):
    admin = _insert_user(db, "admin@example.com", is_admin=True)
    viewer = _insert_user(db, "viewer@example.com")
    nobody = _insert_user(db, "nobody@example.com")
    pending = _insert_user(db, "pending@example.com", status="pending")
    tracker_a = _insert_tracker(db, "A")
    tracker_b = _insert_tracker(db, "B")
    for user_id, tracker_id, role in ((viewer, tracker_a, "viewer"), (pending, tracker_b, "owner")):
        db.execute(
            text("INSERT INTO tracker_roles (user_id, tracker_id, role) VALUES (:u, :t, :r)"),
            {"u": user_id, "t": tracker_id, "r": role},
        )
    existing_user_row = _insert_audit(db, "user", str(viewer))
    missing_user_row = _insert_audit(db, "user", "9999")
    tracker_row = _insert_audit(db, "tracker", str(tracker_a))
    old_visible = {
        admin: [tracker_a, tracker_b],
        viewer: [tracker_a],
        nobody: [],
    }
    db.commit()

    command.upgrade(alembic_config(), "head")

    for user_id, before in old_visible.items():
        assert [t.id for t in visible_trackers(db, db.get(User, user_id))] == before
    targets = {row.id: row.target_user_id for row in db.scalars(select(AuditLog))}
    assert targets == {existing_user_row: viewer, missing_user_row: None, tracker_row: None}
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    assert db.scalar(select(func.count()).select_from(PermissionSet)) == 0
