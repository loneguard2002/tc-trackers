"""My feedback: the sender's list, panel and page, answers, Withdraw and the unread count (database)."""

from __future__ import annotations

import html
import re
from datetime import timedelta

import pytest
from conftest import post, sign_in
from sqlalchemy import select
from test_feedback_service import _png

from tracker.feedback import mail, service
from tracker.mail import smtp
from tracker.models import AppSetting, AuditLog, FeedbackFile, FeedbackMessage, FeedbackRequest

URL = "/feedback/mine"
TEAM = "Progress Tracker team"


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def sam(client, user_factory):
    user = user_factory(full_name="Sam Taylor", email="sam@example.com")
    sign_in(client, user)
    return user


@pytest.fixture
def robin(user_factory, give_set):
    user = user_factory(full_name="Robin Lee", email="robin@example.com")
    give_set(["manage_feedback"], user=user)
    return user


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def mail_on(db):
    db.add_all(
        [
            AppSetting(key="smtp_host", value="smtp.example.com"),
            AppSetting(key="smtp_from", value="pt@example.com"),
            AppSetting(key="feedback_email", value="owner@example.org"),
        ]
    )
    db.commit()


@pytest.fixture
def make(db, sam):
    def create(summary="Add a dark chart theme", kind="idea", details="More colour.", sender=None, status=None):
        made = service.create_request(db, sender or sam, kind, summary, details, "Report", "/report", "Edge", [])
        if status:
            made.status = status
        db.commit()
        return made

    return create


def ask(db, made, reviewer, kind="question", body="Which browser?"):
    message = service.reviewer_reply(db, made, reviewer, kind, body, [])
    db.commit()
    return message


def answer(client, request_id, body="Chrome", **kwargs):
    return post(client, f"{URL}/{request_id}/message", {"body": body}, content_type="multipart/form-data", **kwargs)


def reload(db, made):
    db.expire_all()
    return db.get(FeedbackRequest, made.id)


# ---- the sidebar --------------------------------------------------------------------------------------------------


def test_the_sidebar_shows_my_feedback_only_once_the_person_has_a_request(client, sam, make, db, robin):
    assert "My feedback" not in text_of(client.get("/"))
    made = make()
    page = text_of(client.get("/"))
    assert 'href="/feedback/mine"' in page and "My feedback" in page
    assert "nav-count" not in page.split("My feedback")[1].split("</a>")[0]
    ask(db, made, robin)
    assert re.search(r"My feedback</span><span class=\"nav-count\"[^>]*>1", text_of(client.get("/")))


def test_the_count_is_the_requests_with_an_unopened_reply_and_opening_clears_it(client, sam, make, db, robin):
    first, second = make("First"), make("Second")
    make("Third")
    ask(db, first, robin)
    ask(db, second, robin, "update", "Planned.")
    assert service.mine_counts(db, sam.id) == (3, 2)
    client.get(f"{URL}/{first.id}")
    assert service.mine_counts(db, sam.id) == (3, 1)


def test_the_sidebar_asks_one_query_for_the_count(client, sam, make, db, robin, app):
    from sqlalchemy import event

    from tracker.db import get_engine

    ask(db, make(), robin)
    seen = []

    def count(conn, cursor, statement, *args):
        if "feedback_requests" in statement and "count(" in statement.lower():
            seen.append(statement)

    engine = get_engine(app)
    event.listen(engine, "before_cursor_execute", count)
    try:
        client.get("/")
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(seen) == 1


# ---- the list -----------------------------------------------------------------------------------------------------


def test_the_list_shows_only_the_persons_own_requests_with_the_new_reply_mark(
    client, sam, make, db, robin, user_factory
):
    mine, quiet = make("Mine with a reply"), make("Mine quiet")
    other = make("Someone else's", sender=user_factory(full_name="Pat Doe"))
    ask(db, mine, robin)
    page = text_of(client.get(URL))
    assert "Mine with a reply" in page and "Mine quiet" in page
    assert "Someone else" not in page and "Pat Doe" not in page
    for heading in ("Summary", "Kind", "Sent", "Status", "Last activity"):
        assert f"data-sort-label>{heading}</span>" in page
    row = page.split(f'id="request-{mine.id}"')[1].split("</tr>")[0]
    assert "New reply" in row
    assert "New reply" not in page.split(f'id="request-{quiet.id}"')[1].split("</tr>")[0]
    assert str(other.id) not in re.findall(r'id="request-(\d+)"', page)


def test_the_list_answers_for_a_person_with_no_requests_and_with_the_link_switched_off(client, sam, make, db):
    assert client.get(URL).status_code == 200
    db.add(AppSetting(key="feedback_link", value="0"))
    db.commit()
    made = make()
    assert client.get(URL).status_code == 200
    assert client.get(f"{URL}/{made.id}").status_code == 200
    assert answer(client, made.id).status_code == 302


def test_anonymous_goes_to_sign_in(app):
    assert app.test_client().get(URL).status_code in (302, 303)


# ---- a request ----------------------------------------------------------------------------------------------------


def test_another_persons_request_is_404_everywhere(client, sam, make, db, robin, user_factory):
    theirs = make(sender=user_factory(full_name="Pat Doe"))
    for path in (f"{URL}/{theirs.id}", f"{URL}/{theirs.id}/panel", "/feedback/mine/999", f"{URL}/{theirs.id}/panel"):
        assert client.get(path).status_code == 404
    assert answer(client, theirs.id).status_code == 404
    assert post(client, f"{URL}/{theirs.id}/withdraw").status_code == 404
    assert reload(db, theirs).status == "new"
    # a reviewer reads it in Admin, not here
    sign_in(client, robin)
    assert client.get(f"{URL}/{theirs.id}").status_code == 404


def test_the_emailed_link_opens_the_request_for_its_sender_only(client, app, sam, make, db, robin):
    made = make()
    message = ask(db, made, robin, "update", "Planned.")
    with app.test_request_context():
        body = mail.build_reply_email(db, made, message).get_body(("html",)).get_content()
    link = re.search(r'href="([^"]+/feedback/mine/\d+)"', body).group(1)
    path = "/" + link.split("://", 1)[1].split("/", 1)[1]
    assert path == f"{URL}/{made.id}"
    page = client.get(path)
    assert page.status_code == 200 and "Planned." in text_of(page)
    sign_in(client, robin)
    assert client.get(path).status_code == 404


def test_reviewers_show_as_the_team_and_email_notes_are_left_out(client, sam, make, db, robin, mail_on, monkeypatch):
    made = make()
    monkeypatch.setattr(smtp, "send_message", lambda m: (_ for _ in ()).throw(RuntimeError("down")))
    mail.notify_owner(db, made, db.scalars(select(FeedbackMessage)).first())
    ask(db, made, robin, "update", "We looked at it.")
    service.set_status(db, made, robin, "planned")
    db.commit()
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.role == "system")).all()
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert TEAM in page and "We looked at it." in page and "Status: Planned" in page
    assert "Robin Lee" not in page
    assert "Email not sent" not in page and "mail server" not in page
    assert "Sam Taylor" in page  # the sender's own message


def test_opening_clears_the_mark_and_keeps_the_activity_time(client, sam, make, db, robin):
    made = make()
    ask(db, made, robin)
    before = reload(db, made).last_activity_at
    assert service.has_new_reply(made)
    panel = client.get(f"{URL}/{made.id}/panel")
    assert panel.status_code == 200 and "data-panel-feedback" in panel.get_data(as_text=True)
    assert panel.headers["X-Panel-Changed"] == "1"
    assert "<html" not in panel.get_data(as_text=True)
    again = reload(db, made)
    assert not service.has_new_reply(again) and again.last_activity_at == before
    assert client.get(f"{URL}/{made.id}/panel").headers["X-Panel-Changed"] == "0"


def test_the_box_says_your_answer_when_waiting_and_add_a_message_otherwise(client, sam, make, db, robin):
    made = make()
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert "Add a message" in page and "Your answer" not in page
    ask(db, made, robin)  # a question sets Waiting for an answer
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert "Your answer" in page and "Add a message" not in page
    assert "Goes to the team, and the request moves back to Under review." in page
    assert "Withdraw request" in page


# ---- answering ----------------------------------------------------------------------------------------------------


def test_an_answer_moves_waiting_to_under_review_and_emails_the_feedback_address(
    client, sam, make, db, robin, mail_on, outbox
):
    made = make()
    ask(db, made, robin)
    response = answer(client, made.id, "Chrome on Windows")
    assert response.status_code == 302
    kept = reload(db, made)
    assert kept.status == "under_review"
    last = db.scalars(
        select(FeedbackMessage).where(FeedbackMessage.role == "sender").order_by(FeedbackMessage.id)
    ).all()[-1]
    assert (last.kind, last.body, last.author_id) == ("message", "Chrome on Windows", sam.id)
    assert len(outbox) == 1
    assert outbox[0]["To"] == "owner@example.org"
    assert outbox[0]["Subject"] == f"Sam Taylor answered: Add a dark chart theme ({service.reference(made.id)})"
    row = db.scalars(select(AuditLog).where(AuditLog.action == "feedback_answered")).one()
    assert row.detail["after"] == "under_review" and "Chrome" not in str(row.detail)
    assert "Answer sent." in text_of(client.get(f"{URL}/{made.id}"))


def test_a_message_on_an_open_request_keeps_its_status_and_takes_files(client, sam, make, db, mail_on, outbox):
    made = make(status="planned")
    response = post(
        client,
        f"{URL}/{made.id}/message",
        {"body": "One more thing", "files": (__import__("io").BytesIO(_png()), "shot.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert reload(db, made).status == "planned"
    assert db.scalars(select(FeedbackFile.filename)).all() == ["shot.png"]
    assert len(outbox) == 1


def test_a_message_is_kept_when_email_is_not_set_up(client, sam, make, db):
    made = make()
    assert answer(client, made.id, "Still kept").status_code == 302
    assert "Still kept" in db.scalars(select(FeedbackMessage.body)).all()


def test_an_empty_or_long_message_is_refused_with_the_reason(client, sam, make, db, robin, outbox):
    made = make()
    page = text_of(answer(client, made.id, "  "))
    assert "Write your message." in page
    ask(db, made, robin)
    assert "Write your answer." in text_of(answer(client, made.id, ""))
    long = answer(client, made.id, "x" * 5001)
    assert long.status_code == 400 and "Keep this to 5,000 characters at most." in text_of(long)
    assert reload(db, made).status == "waiting" and outbox == []


def test_the_panel_gets_the_panel_back_after_an_answer(client, sam, make, db, mail_on, outbox):
    made = make()
    response = post(
        client,
        f"{URL}/{made.id}/message",
        {"body": "From the panel"},
        content_type="multipart/form-data",
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200 and response.headers["X-Panel-Changed"] == "1"
    body = response.get_data(as_text=True)
    assert "data-panel-feedback" in body and "From the panel" in body and "Message sent." in body


# ---- withdrawing --------------------------------------------------------------------------------------------------


def test_withdraw_asks_first_then_withdraws_without_email(client, sam, make, db, mail_on, outbox):
    made = make()
    asked = text_of(client.get(f"{URL}/{made.id}?withdraw=1"))
    assert "Withdraw this request? The team will see that you withdrew it." in asked
    plain = client.get(f"{URL}/{made.id}").get_data(as_text=True)
    assert re.search(r"data-withdraw-confirm\s+hidden", plain)  # shown only after the question is asked
    assert "window.confirm" not in plain
    assert post(client, f"{URL}/{made.id}/withdraw").status_code == 302
    assert reload(db, made).status == "withdrawn"
    assert outbox == []
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert "Status: Withdrawn" in page and "Your answer" not in page and "Add a message" not in page
    assert "Withdraw request" not in page
    assert db.scalars(select(AuditLog).where(AuditLog.action == "feedback_withdrawn")).one()


# ---- a closed request is read-only ---------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["done", "will_not_do", "withdrawn"])
def test_a_closed_request_is_read_only(client, sam, make, db, status, outbox):
    made = make(status=status)
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert "Add a message" not in page and "Your answer" not in page and "Withdraw request" not in page
    for refused in (answer(client, made.id), post(client, f"{URL}/{made.id}/withdraw")):
        assert refused.status_code == 302
    assert "This request is closed, so it cannot be changed." in text_of(client.get(f"{URL}/{made.id}"))
    fetched = post(
        client,
        f"{URL}/{made.id}/message",
        {"body": "x"},
        content_type="multipart/form-data",
        headers={"X-Requested-With": "fetch"},
    )
    assert fetched.status_code == 409 and "This request is closed" in fetched.get_data(as_text=True)
    kept = reload(db, made)
    assert kept.status == status and len(db.scalars(select(FeedbackMessage)).all()) == 1
    assert outbox == []


def test_a_reply_after_the_sender_opened_marks_it_again(client, sam, make, db, robin):
    made = make()
    client.get(f"{URL}/{made.id}")
    assert service.mine_counts(db, sam.id) == (1, 0)
    reload(db, made).sender_seen_at -= timedelta(minutes=5)
    ask(db, made, robin, "update", "Later")
    assert service.mine_counts(db, sam.id) == (1, 1)
