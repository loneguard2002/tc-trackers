import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _request(db, user_id=None):
    return db.execute(
        text("INSERT INTO feedback_requests (kind, summary, sender_id) VALUES ('idea', 'S', :u) RETURNING id"),
        {"u": user_id},
    ).scalar_one()


def test_the_defaults_and_indexes(db):
    _request(db)
    row = db.execute(
        text(
            "SELECT status, details, page_title, page_url, browser, email_note, sender_seen_at, "
            "created_at IS NOT NULL, last_activity_at IS NOT NULL FROM feedback_requests"
        )
    ).one()
    assert row == ("new", "", "", "", "", "", None, True, True)
    names = set(db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename LIKE 'feedback_%'")).scalars())
    assert {
        "ix_feedback_requests_status_last_activity_at",
        "ix_feedback_requests_sender_id",
        "ix_feedback_messages_request_id_id",
    } <= names
    db.rollback()


def test_the_checks_refuse_other_values(db):
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO feedback_requests (kind, summary) VALUES ('rant', 'S')"))
    db.rollback()
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO feedback_requests (kind, summary, status) VALUES ('idea', 'S', 'open')"))
    db.rollback()
    request_id = _request(db)
    with pytest.raises(IntegrityError):
        db.execute(
            text("INSERT INTO feedback_messages (request_id, role, kind) VALUES (:r, 'sender', 'chat')"),
            {"r": request_id},
        )
    db.rollback()


def test_messages_and_files_go_with_the_request_and_the_request_survives_the_person(db, user_factory):
    user = user_factory()
    request_id = _request(db, user.id)
    message_id = db.execute(
        text("INSERT INTO feedback_messages (request_id, role, kind) VALUES (:r, 'sender', 'message') RETURNING id"),
        {"r": request_id},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO feedback_files (request_id, message_id, filename, content_type, size, data) "
            "VALUES (:r, :m, 'a.txt', 'text/plain', 1, 'x')"
        ),
        {"r": request_id, "m": message_id},
    )
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user.id})
    assert db.execute(text("SELECT sender_id FROM feedback_requests")).scalar_one() is None
    db.execute(text("DELETE FROM feedback_requests"))
    for table in ("feedback_messages", "feedback_files"):
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    db.rollback()


def test_downgrade_drops_the_tables(db):
    try:
        command.downgrade(alembic_config(), "0014")
        for table in ("feedback_requests", "feedback_messages", "feedback_files"):
            assert db.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one() is None
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
