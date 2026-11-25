"""Feedback rules: files, requests, replies, statuses, unread marks and settings (database required)."""

import io
import struct
import zlib

import pytest
from sqlalchemy import select
from werkzeug.datastructures import FileStorage

from tracker.auth.permissions import PERMISSION_GROUPS, PERMISSIONS
from tracker.feedback import service, settings
from tracker.models import AppSetting, AuditLog, FeedbackFile, FeedbackMessage


def _png() -> bytes:
    def chunk(kind, body):
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


def upload(name, data):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def test_reference_pads_to_four_digits():
    assert service.reference(42) == "FB-0042"
    assert service.reference(12345) == "FB-12345"


def test_statuses():
    assert service.OPEN == ("new", "under_review", "waiting", "planned")
    assert service.CLOSED == ("done", "will_not_do", "withdrawn")
    assert len(service.STATUS_LABELS) == len(service.STATUSES) == 7


def test_check_files_accepts_content_that_matches_its_name():
    files = [
        upload("shot.png", _png()),
        upload("doc.pdf", b"%PDF-1.7\n%..."),
        upload("a.docx", b"PK\x03\x04rest"),
        upload("b.xlsx", b"PK\x03\x04rest"),
        upload("n.txt", "caf\u00e9".encode()),
    ]
    valid, errors = service.check_files(files)
    assert errors == []
    assert [(v.filename, v.content_type) for v in valid] == [
        ("shot.png", "image/png"),
        ("doc.pdf", "application/pdf"),
        ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("b.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("n.txt", "text/plain"),
    ]
    assert valid[0].data == _png()


def test_check_files_ignores_an_empty_file_field():
    assert service.check_files([upload("", b"")]) == ([], [])


def test_check_files_refuses_a_sixth_file():
    files = [upload(f"{n}.png", _png()) for n in range(6)]
    assert service.check_files(files) == ([], ["Attach at most 5 files."])


def test_check_files_refuses_a_file_over_5_mb():
    big = _png() + b"\x00" * (6 * 1024 * 1024)
    assert service.check_files([upload("big.png", big)]) == ([], ["big.png is over 5 MB."])


@pytest.mark.parametrize(
    "name,data",
    [
        ("tool.exe", b"MZ\x90\x00"),
        ("shot.png", b"<!DOCTYPE html><html><script>alert(1)</script></html>"),
        ("shot.png", b"  \n<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("note.txt", b"<html><body>hi</body></html>"),
        ("note.txt", b"hello <svg onload=alert(1)>"),
        ("note.txt", b"<b>bold</b>"),
        ("note.txt", b"nul\x00byte"),
        ("note.txt", b"\xff\xfe\x00bad"),
        ("note.csv", b"\xc3\x28"),
        ("renamed.jpg", _png()),
        ("fake.pdf", b"not a pdf"),
        ("fake.docx", b"not a zip"),
        ("archive.zip", b"PK\x03\x04rest"),
        ("noextension", b"%PDF-1.7"),
    ],
)
def test_check_files_refuses_by_content_and_name(name, data):
    assert service.check_files([upload(name, data)]) == (
        [],
        [f"{name} is not a picture, PDF, Word, Excel or text file."],
    )


def test_check_files_names_every_refused_file():
    _, errors = service.check_files([upload("a.exe", b"MZ"), upload("b.png", _png()), upload("c.png", b"<html>")])
    assert errors == [
        "a.exe is not a picture, PDF, Word, Excel or text file.",
        "c.png is not a picture, PDF, Word, Excel or text file.",
    ]


def test_check_files_keeps_only_the_file_name():
    valid, _ = service.check_files([upload("C:\\Users\\me\\shot.png", _png())])
    assert valid[0].filename == "shot.png"


@pytest.fixture
def people(user_factory):
    return user_factory(full_name="Sender"), user_factory(full_name="Reviewer")


@pytest.fixture
def sent(db, people):
    sender, _ = people
    files = [service.ValidFile("shot.png", "image/png", _png())]
    request = service.create_request(
        db, sender, "problem", "A secret summary", "Secret details", "Page", "/page", "Edge", files
    )
    db.commit()
    return request


def activity(db):
    return db.scalars(select(AuditLog).order_by(AuditLog.id)).all()


def test_create_request_keeps_the_request_one_message_and_its_files(db, people, sent):
    sender, _ = people
    assert (sent.status, sent.kind, sent.sender_id, sent.page_url) == ("new", "problem", sender.id, "/page")
    messages = db.scalars(select(FeedbackMessage)).all()
    assert [(m.role, m.kind, m.body) for m in messages] == [("sender", "message", "Secret details")]
    stored = db.scalars(select(FeedbackFile)).all()
    assert [(f.filename, f.size, f.message_id, f.request_id) for f in stored] == [
        ("shot.png", len(_png()), messages[0].id, sent.id)
    ]
    rows = activity(db)
    assert len(rows) == 1
    assert (rows[0].action, rows[0].entity, rows[0].entity_id, rows[0].user_id) == (
        "feedback_sent",
        "feedback",
        str(sent.id),
        sender.id,
    )
    assert rows[0].detail == {"reference": service.reference(sent.id), "kind": "problem"}


def test_functions_do_not_commit(db, people):
    sender, _ = people
    service.create_request(db, sender, "idea", "S", "", "", "", "", [])
    db.rollback()
    assert db.scalars(select(FeedbackMessage)).all() == []
    assert activity(db) == []


def test_a_question_sets_waiting_and_an_update_leaves_the_status(db, people, sent):
    _, reviewer = people
    service.set_status(db, sent, reviewer, "planned")
    service.reviewer_reply(db, sent, reviewer, "update", "Soon", [])
    assert sent.status == "planned"
    service.reviewer_reply(db, sent, reviewer, "question", "Which browser?", [])
    assert sent.status == "waiting"
    assert service.replies(sent) == 2


def test_a_reviewer_may_reply_to_and_restatus_a_withdrawn_request(db, people, sent):
    _, reviewer = people
    service.withdraw(db, sent)
    service.reviewer_reply(db, sent, reviewer, "update", "Noted", [])
    assert sent.status == "withdrawn"
    service.reviewer_reply(db, sent, reviewer, "question", "Still there?", [])
    assert sent.status == "waiting"
    service.set_status(db, sent, reviewer, "done")
    assert sent.status == "done"


def test_set_status_notes_it_and_refuses_an_unknown_status(db, people, sent):
    _, reviewer = people
    service.set_status(db, sent, reviewer, "under_review")
    note = db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "status")).one()
    assert (note.role, note.status_from, note.status_to, note.author_id) == (
        "reviewer",
        "new",
        "under_review",
        reviewer.id,
    )
    service.set_status(db, sent, reviewer, "under_review")  # no change, no entry
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "status")).all() == [note]
    with pytest.raises(ValueError):
        service.set_status(db, sent, reviewer, "open")


def test_the_sender_answering_a_question_moves_it_to_under_review(db, people, sent):
    _, reviewer = people
    service.reviewer_reply(db, sent, reviewer, "question", "Which browser?", [])
    service.sender_message(db, sent, "Edge", [])
    assert sent.status == "under_review"
    service.sender_message(db, sent, "More", [])
    assert sent.status == "under_review"
    assert [a.action for a in activity(db)][-2:] == ["feedback_answered", "feedback_answered"]


def test_the_sender_cannot_add_to_a_closed_request(db, people, sent):
    _, reviewer = people
    service.set_status(db, sent, reviewer, "done")
    with pytest.raises(ValueError):
        service.sender_message(db, sent, "Please reopen", [])


def test_withdraw_sets_withdrawn_and_refuses_a_closed_request(db, people, sent):
    _, reviewer = people
    service.withdraw(db, sent)
    assert sent.status == "withdrawn"
    with pytest.raises(ValueError):
        service.withdraw(db, sent)
    service.set_status(db, sent, reviewer, "done")
    with pytest.raises(ValueError):
        service.withdraw(db, sent)


def test_activity_never_holds_feedback_content(db, people, sent):
    _, reviewer = people
    service.reviewer_reply(
        db, sent, reviewer, "question", "Secret reply", [service.ValidFile("secret.png", "image/png", b"x")]
    )
    service.set_status(db, sent, reviewer, "planned")
    service.sender_message(db, sent, "Secret answer", [])
    service.withdraw(db, sent)
    rows = activity(db)
    assert [r.action for r in rows] == [
        "feedback_sent",
        "feedback_replied",
        "feedback_status",
        "feedback_answered",
        "feedback_withdrawn",
    ]
    assert rows[1].detail == {
        "reference": service.reference(sent.id),
        "kind": "problem",
        "reply": "question",
        "before": "new",
        "after": "waiting",
    }
    assert (rows[2].detail["before"], rows[2].detail["after"]) == ("waiting", "planned")
    for row in rows:
        assert row.entity == "feedback"
        assert "secret" not in str(row.detail).lower()


def test_last_activity_moves_with_each_change(db, people, sent):
    _, reviewer = people
    first = sent.last_activity_at
    service.reviewer_reply(db, sent, reviewer, "update", "Hello", [])
    second = sent.last_activity_at
    assert second > first
    service.set_status(db, sent, reviewer, "planned")
    assert sent.last_activity_at > second


def test_a_reply_or_status_change_is_new_until_the_sender_opens_it(db, people, sent):
    sender, reviewer = people
    assert service.has_new_reply(sent) is False
    assert service.unread_count(db, sender.id) == 0
    service.reviewer_reply(db, sent, reviewer, "update", "Hello", [])
    assert service.has_new_reply(sent) is True
    assert service.unread_count(db, sender.id) == 1
    service.mark_seen(db, sent)
    assert service.has_new_reply(sent) is False
    assert service.unread_count(db, sender.id) == 0
    service.set_status(db, sent, reviewer, "planned")
    assert service.has_new_reply(sent) is True
    service.mark_seen(db, sent)
    service.sender_message(db, sent, "Thanks", [])  # the sender's own message is not a reply
    assert service.has_new_reply(sent) is False


def test_unread_count_is_per_sender(db, people, sent, user_factory):
    _, reviewer = people
    other = user_factory()
    service.reviewer_reply(db, sent, reviewer, "update", "Hello", [])
    assert service.unread_count(db, other.id) == 0


def test_new_count_and_replies(db, people, sent):
    _, reviewer = people
    assert service.new_count(db) == 1
    service.set_status(db, sent, reviewer, "under_review")
    assert service.new_count(db) == 0
    service.reviewer_reply(db, sent, reviewer, "update", "A", [])
    service.reviewer_reply(db, sent, reviewer, "question", "B", [])
    service.sender_message(db, sent, "C", [])
    assert service.replies(sent) == 2  # not the status change, nor the sender's messages


def test_parse_addresses():
    assert settings.parse_addresses("a@x.com, b@y.org") == (["a@x.com", "b@y.org"], None)
    assert settings.parse_addresses("") == ([], None)
    assert settings.parse_addresses(" a@x.com ,, ") == (["a@x.com"], None)
    assert settings.parse_addresses("a@x.com, nonsense") == ([], "Enter valid email addresses, separated by commas.")
    assert settings.parse_addresses("a@x.com b@y.org") == ([], "Enter valid email addresses, separated by commas.")
    ten = ", ".join(f"p{n}@x.com" for n in range(10))
    assert settings.parse_addresses(ten)[1] is None
    assert settings.parse_addresses(ten + ", q@x.com") == ([], "Enter at most 10 addresses.")


def test_settings_are_read_from_app_settings(db):
    assert settings.addresses(db) == []
    assert settings.link_on(db) is True
    db.add_all(
        [AppSetting(key=settings.ADDRESS_KEY, value="a@x.com,b@y.org"), AppSetting(key=settings.LINK_KEY, value="0")]
    )
    db.commit()
    assert settings.addresses(db) == ["a@x.com", "b@y.org"]
    assert settings.link_on(db) is False


def test_manage_feedback_is_in_the_application_group():
    assert PERMISSIONS["manage_feedback"][0] == "Manage feedback"
    assert PERMISSIONS["manage_feedback"][1] == "Read, reply to and change the status of feedback in Admin › Feedback."
    groups = dict(PERMISSION_GROUPS)
    assert "manage_feedback" in groups["Application"]


def test_sender_and_reviewer_files_are_stored_with_their_message(db, people, sent):
    _, reviewer = people
    reply = service.reviewer_reply(db, sent, reviewer, "update", "See", [service.ValidFile("r.png", "image/png", b"r")])
    answer = service.sender_message(db, sent, "Here", [service.ValidFile("s.txt", "text/plain", b"ss")])
    stored = {f.filename: (f.message_id, f.request_id, f.size) for f in db.scalars(select(FeedbackFile))}
    assert stored["r.png"] == (reply.id, sent.id, 1)
    assert stored["s.txt"] == (answer.id, sent.id, 2)


def test_mark_seen_is_not_activity(db, people, sent):
    before = sent.last_activity_at
    service.mark_seen(db, sent)
    assert sent.sender_seen_at is not None
    assert sent.last_activity_at == before


def test_withdraw_notes_the_change_in_the_conversation(db, people, sent):
    sender, _ = people
    service.set_status(db, sent, people[1], "planned")
    service.withdraw(db, sent)
    note = db.scalars(select(FeedbackMessage).order_by(FeedbackMessage.id.desc())).first()
    assert (note.role, note.kind, note.status_from, note.status_to, note.author_id) == (
        "sender",
        "status",
        "planned",
        "withdrawn",
        sender.id,
    )
