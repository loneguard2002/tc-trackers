"""Admin › Feedback: the table, the review panel and page, replies, statuses and the files route (database)."""

from __future__ import annotations

import html
import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from conftest import post, sign_in
from sqlalchemy import select
from test_feedback_service import _png

from tracker.feedback import mail, service
from tracker.feedback.service import ValidFile
from tracker.mail import smtp
from tracker.models import AppSetting, AuditLog, FeedbackFile, FeedbackMessage, FeedbackRequest

URL = "/admin/feedback"
PDF = b"%PDF-1.4\n% a test\n"


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


@pytest.fixture
def sam(user_factory):
    return user_factory(full_name="Sam Taylor", email="sam@example.com")


@pytest.fixture
def reviewer(client, user_factory, give_set):
    user = user_factory(full_name="Robin Lee", email="robin@example.com")
    give_set(["manage_feedback"], user=user)
    sign_in(client, user)
    return user


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def mail_on(db):
    db.add_all(
        [AppSetting(key="smtp_host", value="smtp.example.com"), AppSetting(key="smtp_from", value="pt@example.com")]
    )
    db.commit()


@pytest.fixture
def make(db, sam):
    def create(summary="Add a dark chart theme", kind="idea", details="", files=(), sender=None, status=None, **page):
        made = service.create_request(
            db,
            sender or sam,
            kind,
            summary,
            details,
            page.get("page_title", "Core Rollout › Report"),
            page.get("page_url", "/trackers/1/report"),
            "Edge on Windows",
            list(files),
        )
        if status:
            made.status = status
        db.commit()
        return made

    return create


def reply(client, request_id, data=None, files=None, **kwargs):
    payload = {"kind": "update", "body": "We have planned it.", "email": "1", **(data or {})}
    payload.update(files or {})
    return post(client, f"{URL}/{request_id}/reply", payload, content_type="multipart/form-data", **kwargs)


# ---- who reaches the pages -----------------------------------------------------------------------------------------


def test_anonymous_goes_to_sign_in(client):
    assert client.get(URL).status_code in (302, 303)


def test_people_without_manage_feedback_are_refused(client, logged_in_user, make, outbox):
    made = make()
    assert client.get(URL).status_code == 403
    # a request, its panel and its forms answer 404, so that guessing an id tells nothing
    assert client.get(f"{URL}/{made.id}").status_code == 404
    assert client.get(f"{URL}/{made.id}/panel").status_code == 404
    assert post(client, f"{URL}/{made.id}/status", {"status": "planned"}).status_code == 404
    assert reply(client, made.id).status_code == 404
    assert outbox == []


def test_holders_and_administrators_reach_the_pages(client, reviewer, make, user_factory):
    made = make()
    assert client.get(URL).status_code == 200
    assert client.get(f"{URL}/{made.id}").status_code == 200
    assert client.get(f"{URL}/{made.id}/panel").status_code == 200
    admin = client.application.test_client()
    sign_in(admin, user_factory(is_admin=True))
    assert admin.get(URL).status_code == 200
    assert admin.get(f"{URL}/{made.id}").status_code == 200


def test_an_unknown_request_is_404(client, reviewer):
    assert client.get(f"{URL}/999").status_code == 404
    assert client.get(f"{URL}/99999999999999999999/panel").status_code == 404


def test_the_pages_keep_working_with_the_feedback_link_switched_off(client, reviewer, make, db):
    made = make()
    db.add(AppSetting(key="feedback_link", value="0"))
    db.commit()
    assert client.get(URL).status_code == 200
    assert client.get(f"{URL}/{made.id}").status_code == 200
    assert reply(client, made.id).status_code == 302


def test_the_link_in_the_feedback_email_opens_the_request(client, app, reviewer, make, db):
    made = make()
    first = db.scalars(select(FeedbackMessage).where(FeedbackMessage.request_id == made.id)).one()
    with app.test_request_context():
        page = mail.build_email(db, made, first, ["owner@example.org"]).get_body(("html",)).get_content()
    link = re.search(r'href="([^"]+)"[^>]*>Open in Progress Tracker', page).group(1)
    path = "/" + link.split("://", 1)[1].split("/", 1)[1]
    assert path == f"{URL}/{made.id}"
    assert client.get(path).status_code == 200


# ---- the sidebar ---------------------------------------------------------------------------------------------------


def test_the_sidebar_shows_feedback_with_the_new_count(client, reviewer, make):
    make()
    make(summary="Second")
    make(summary="Planned one", status="planned")
    page = client.get("/").get_data(as_text=True)
    link = re.search(r'<a class="nav-link[^"]*" href="/admin/feedback"[^>]*>.*?</a>', page, re.S).group(0)
    assert "<span>Feedback</span>" in link
    assert '<span class="nav-count" title="new">2<span class="sr-only"> new</span>' in link


def test_the_sidebar_has_no_feedback_for_others(client, logged_in_user, make):
    make()
    assert 'href="/admin/feedback"' not in client.get("/").get_data(as_text=True)


# ---- the table -----------------------------------------------------------------------------------------------------


def test_the_table_has_the_standard_tools(client, reviewer, make, db):
    old = make(summary="Older idea", details="Some long words", page_title="Trackers", page_url="/")
    new = make(summary="Chart is blank", kind="problem", details="Nothing shows")
    closed = make(summary="Done one", status="done")
    old.last_activity_at = datetime.now(timezone.utc) - timedelta(days=3)
    closed.last_activity_at = datetime.now(timezone.utc) - timedelta(days=5)
    db.commit()
    page = client.get(URL).get_data(as_text=True)

    assert 'id="feedback-table-search"' in page
    kinds = re.search(r'<select[^>]*data-region-filter="feedback-table"[^>]*>(.*?)</select>', page, re.S).group(1)
    assert re.findall(r'<option value="([a-z]*)"[^>]*>([^<]+)</option>', kinds) == [
        ("", "Ideas and problems"),
        ("idea", "Ideas"),
        ("problem", "Problems"),
    ]
    buttons = re.findall(
        r'data-status="([a-z]+)" aria-pressed="(true|false)">([^<]+) <span class="chip-count[^"]*" data-count>(\d+)',
        page,
    )
    assert buttons == [
        ("open", "true", "Open", "2"),
        ("new", "false", "New", "2"),
        ("waiting", "false", "Waiting for an answer", "0"),
        ("planned", "false", "Planned", "0"),
        ("closed", "false", "Closed", "1"),
        ("all", "false", "All", "3"),
    ]
    headings = re.findall(r'<button type="button" class="sort-button" data-sort="([a-z]+)" hidden>([^<]+)<', page)
    assert headings == [
        ("ref", "Ref"),
        ("activity", "Last activity"),
        ("kind", "Kind"),
        ("summary", "Summary"),
        ("from", "From"),
        ("page", "Page"),
        ("status", "Status"),
        ("replies", "Replies"),
    ]
    assert 'data-sort-type="date"' in page and 'data-sort-type="number"' in page
    assert "Showing 3 of 3 requests · 2 open" in html.unescape(page)
    assert 'data-active-token="open"' in page
    # newest activity first
    assert page.index(f'data-request="{new.id}"') < page.index(f'data-request="{old.id}"')
    assert page.index(f'data-request="{old.id}"') < page.index(f'data-request="{closed.id}"')
    row = re.search(rf'<tr[^>]*data-request="{old.id}"[^>]*>', page).group(0)
    search = re.search(r'data-search="([^"]*)"', row).group(1)
    for part in ("fb-0001", "older idea", "some long words", "sam taylor", "trackers"):
        assert part in html.unescape(search)
    assert 'data-status="open new"' in row and 'data-region="idea"' in row
    closed_row = re.search(rf'<tr[^>]*data-request="{closed.id}"[^>]*>', page).group(0)
    assert 'data-status="closed done"' in closed_row
    assert f'href="{URL}/{old.id}"' in page


def test_the_replies_column_counts_updates_and_questions_only(client, reviewer, make, db, sam):
    made = make()
    service.reviewer_reply(db, made, reviewer, "update", "One", [])
    service.reviewer_reply(db, made, reviewer, "question", "Two?", [])
    service.set_status(db, made, reviewer, "planned")
    service.sender_message(db, made, "An answer", [])
    db.commit()
    row = re.search(rf'<tr[^>]*data-request="{made.id}"[^>]*>', client.get(URL).get_data(as_text=True)).group(0)
    assert 'data-sort-replies="2"' in row


def test_an_empty_table_says_so(client, reviewer):
    assert "No feedback yet." in client.get(URL).get_data(as_text=True)


def test_the_kind_chosen_in_the_address_is_selected(client, reviewer, make):
    make()
    page = client.get(URL + "?region=problem").get_data(as_text=True)
    assert '<option value="problem" selected>Problems</option>' in page


# ---- the panel and the page ----------------------------------------------------------------------------------------


def test_the_panel_shows_the_head_the_conversation_and_the_status(client, reviewer, make, db):
    made = make(
        details="It would help at night.",
        files=[ValidFile("shot.png", "image/png", _png()), ValidFile("notes.pdf", "application/pdf", PDF)],
    )
    service.reviewer_reply(db, made, reviewer, "question", "Which charts?", [])
    service.set_status(db, made, reviewer, "planned")
    db.commit()
    response = client.get(f"{URL}/{made.id}/panel")
    page = text_of(response)
    assert "<html" not in page and "data-panel-feedback" in page
    assert "Idea · FB-0001" in page
    assert "Received" in page
    assert "Add a dark chart theme" in page
    assert re.search(r'From Sam Taylor · <a href="/trackers/1/report">Core Rollout › Report</a>', page)
    statuses = re.search(r'<select[^>]*name="status"[^>]*>(.*?)</select>', page, re.S).group(1)
    assert re.findall(r">([^<]+)</option>", statuses) == list(service.STATUS_LABELS)
    assert '<option value="planned" selected>' in statuses
    # oldest first: the sender's message, the question, the status change
    assert page.index("It would help at night.") < page.index("Which charts?") < page.index("Status: Planned")
    assert "Question" in page
    files = {f.filename: f.id for f in db.scalars(select(FeedbackFile))}
    assert re.search(rf'<img[^>]*src="/feedback/files/{files["shot.png"]}"[^>]*alt="shot.png"', page)
    assert re.search(
        rf'<a[^>]*href="/feedback/files/{files["notes.pdf"]}"[^>]*>(<svg.*?</svg>)?notes.pdf</a>', page, re.S
    )
    assert "Your update" in page and "Send the update" in page
    assert re.search(r'<input[^>]*name="email"[^>]*checked', page) and "Email Sam Taylor" in page


def test_the_page_shows_the_same_request_in_the_site(client, reviewer, make):
    made = make()
    page = text_of(client.get(f"{URL}/{made.id}"))
    assert "<html" in page and "data-panel-feedback" in page
    assert "FB-0001" in page and "Add a dark chart theme" in page


def test_a_failed_email_shows_in_the_conversation(client, reviewer, make, db):
    made = make()
    mail.notify_owner(db, made, db.scalars(select(FeedbackMessage)).one())
    db.commit()
    assert "Email not sent: no feedback address set" in text_of(client.get(f"{URL}/{made.id}/panel"))


def test_a_withdrawn_request_says_who_withdrew_it(client, reviewer, make, db):
    made = make()
    service.withdraw(db, made)
    db.commit()
    assert "Status: Withdrawn" in text_of(client.get(f"{URL}/{made.id}/panel"))


# ---- status --------------------------------------------------------------------------------------------------------


def test_a_status_change_is_noted_and_recorded(client, reviewer, make, db):
    made = make()
    response = post(client, f"{URL}/{made.id}/status", {"status": "planned"})
    assert response.status_code == 302 and response.headers["Location"].endswith(f"{URL}/{made.id}")
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "planned"
    note = db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "status")).one()
    assert (note.status_from, note.status_to, note.author_id) == ("new", "planned", reviewer.id)
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "feedback_status")).one()
    assert entry.detail == {"reference": "FB-0001", "kind": "idea", "before": "new", "after": "planned"}


def test_an_unknown_status_is_refused_without_a_change(client, reviewer, make, db):
    made = make()
    assert post(client, f"{URL}/{made.id}/status", {"status": "lost"}).status_code == 400
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "new"


def test_a_status_change_from_the_panel_answers_with_the_panel(client, reviewer, make):
    made = make()
    response = post(client, f"{URL}/{made.id}/status", {"status": "done"}, headers={"X-Requested-With": "fetch"})
    page = text_of(response)
    assert response.status_code == 200 and "data-panel-feedback" in page and "<html" not in page
    assert "Status: Done" in page
    assert response.headers["X-Panel-Changed"] == "1"


def test_saving_the_same_status_says_so_and_changes_nothing(client, reviewer, make, db):
    made = make()
    response = post(client, f"{URL}/{made.id}/status", {"status": "new"}, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200 and response.headers["X-Panel-Changed"] == "0"
    assert "The status is already New." in text_of(response)
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "status")).all() == []
    plain = post(client, f"{URL}/{made.id}/status", {"status": "new"})
    assert plain.status_code == 302
    assert "The status is already New." in text_of(client.get(plain.headers["Location"]))


# ---- replies -------------------------------------------------------------------------------------------------------


def test_a_question_sets_waiting_and_emails_the_sender(client, reviewer, make, db, outbox, mail_on):
    made = make(kind="problem", summary="Chart is blank", details="It is blank.")
    response = reply(client, made.id, {"kind": "question", "body": "Which browser do you use?"})
    assert response.status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "waiting"
    question = db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "question")).one()
    assert question.body == "Which browser do you use?" and question.author_id == reviewer.id
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg["To"] == "sam@example.com"
    assert msg["Reply-To"] == "robin@example.com"
    assert msg["Subject"] == "A question about your report: Chart is blank (FB-0001)"
    body = msg.get_body(("html",)).get_content()
    assert "Which browser do you use?" in body and "Answer in Progress Tracker" in body
    assert f"/feedback/mine/{made.id}" in body
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "feedback_replied")).one()
    assert "Which browser" not in str(entry.detail)


def test_an_update_keeps_the_status_and_has_its_own_subject(client, reviewer, make, db, outbox, mail_on):
    made = make(status="planned")
    assert reply(client, made.id, {"kind": "update", "body": "It is coming next month."}).status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "planned"
    assert outbox[0]["Subject"] == "Update on your idea: Add a dark chart theme (FB-0001)"
    body = outbox[0].get_body(("html",)).get_content()
    assert "See it in Progress Tracker" in body
    assert "From Robin Lee, Progress Tracker team" in body
    assert "Reply to this email to answer Robin Lee directly." in body


def test_an_update_applies_the_status_chosen_in_the_head(client, reviewer, make, db, outbox):
    made = make()
    response = reply(client, made.id, {"kind": "update", "body": "Planned for March.", "status": "planned"})
    assert response.status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "planned"
    kinds = db.scalars(
        select(FeedbackMessage.kind).where(FeedbackMessage.role == "reviewer").order_by(FeedbackMessage.id)
    ).all()
    assert kinds == ["status", "update"]
    assert "Status saved: Planned. Update sent." in text_of(client.get(response.headers["Location"]))


def test_a_question_ends_waiting_whatever_the_head_says(client, reviewer, make, db, outbox):
    made = make()
    assert reply(client, made.id, {"kind": "question", "body": "Which page?", "status": "planned"}).status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "waiting"
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "status")).all() == []


def test_a_reply_with_an_unknown_status_is_refused(client, reviewer, make, db, outbox):
    made = make()
    response = reply(client, made.id, {"status": "lost"})
    assert response.status_code == 400 and "Choose a status from the list." in text_of(response)
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.role == "reviewer")).all() == []


def test_unticking_email_sends_nothing(client, reviewer, make, db, outbox, mail_on):
    made = make()
    payload = {"kind": "question", "body": "Which page?", "email": ""}
    assert reply(client, made.id, payload).status_code == 302
    assert outbox == []
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "waiting"


def test_a_failed_email_to_the_sender_is_noted(client, reviewer, make, db, outbox):
    made = make()  # SMTP is not set up
    assert reply(client, made.id).status_code == 302
    notes = db.scalars(select(FeedbackMessage.body).where(FeedbackMessage.kind == "email")).all()
    assert notes == ["Email to Sam Taylor not sent: email is not set up"]


def test_a_reply_email_the_mail_server_refuses_is_noted(client, reviewer, make, db, mail_on, monkeypatch):
    def refuse(msg):
        raise smtp.MailError("550 no")

    monkeypatch.setattr(smtp, "send_message", refuse)
    made = make()
    response = reply(client, made.id)
    assert response.status_code == 302
    notes = db.scalars(select(FeedbackMessage.body).where(FeedbackMessage.kind == "email")).all()
    assert notes == ["Email to Sam Taylor not sent: the mail server refused it"]
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "update")).one()  # the reply is kept
    assert "Update sent. Email to Sam Taylor not sent: the mail server refused it." in text_of(
        client.get(response.headers["Location"])
    )


def test_an_inactive_sender_cannot_be_emailed(client, reviewer, make, db, outbox, mail_on, sam):
    made = make()
    sam.status = "disabled"
    db.commit()
    page = text_of(client.get(f"{URL}/{made.id}/panel"))
    box = re.search(r'<input[^>]*name="email"[^>]*>', page).group(0)
    assert "disabled" in box and "checked" not in box
    assert "Sam Taylor can no longer be emailed: their account is not active." in page
    assert reply(client, made.id, {"email": "1"}).status_code == 302
    assert outbox == []
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "update")).one()


def test_a_reply_on_a_withdrawn_request_is_allowed(client, reviewer, make, db, outbox):
    made = make()
    service.withdraw(db, made)
    db.commit()
    assert reply(client, made.id, {"kind": "update", "body": "Noted.", "email": ""}).status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "withdrawn"
    assert reply(client, made.id, {"kind": "question", "body": "Still wanted?", "email": ""}).status_code == 302
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "waiting"


def test_a_reply_needs_text_and_keeps_what_was_typed(client, reviewer, make, db, outbox):
    made = make()
    response = reply(client, made.id, {"kind": "question", "body": "  "})
    assert response.status_code == 400
    assert "Write your question." in text_of(response)
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.role == "reviewer")).all() == []
    long = reply(client, made.id, {"body": "x" * 5001})
    assert long.status_code == 400 and "Keep this to 5,000 characters at most." in text_of(long)


def test_a_reply_of_exactly_5000_characters_is_taken(client, reviewer, make, db, outbox):
    made = make()
    assert reply(client, made.id, {"body": "x" * 5000, "email": ""}).status_code == 302
    assert len(db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "update")).one().body) == 5000


def test_a_reply_of_an_unknown_kind_is_kept_as_an_update(client, reviewer, make, db, outbox):
    made = make()
    assert reply(client, made.id, {"kind": "memo", "body": "Noted.", "email": ""}).status_code == 302
    db.expire_all()
    kinds = db.scalars(select(FeedbackMessage.kind).where(FeedbackMessage.role == "reviewer")).all()
    assert kinds == ["update"] and db.get(FeedbackRequest, made.id).status == "new"


def test_a_reply_keeps_its_files_and_refuses_bad_ones(client, reviewer, make, db, outbox):
    made = make()
    refused = reply(client, made.id, files={"files": (io.BytesIO(b"<html></html>"), "shot.png")})
    assert refused.status_code == 400 and "shot.png is not a picture" in text_of(refused)
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.role == "reviewer")).all() == []
    kept = reply(client, made.id, files={"files": (io.BytesIO(_png()), "fix.png")})
    assert kept.status_code == 302
    message = db.scalars(select(FeedbackMessage).where(FeedbackMessage.role == "reviewer")).one()
    assert db.scalars(select(FeedbackFile.filename).where(FeedbackFile.message_id == message.id)).all() == ["fix.png"]


def test_a_reply_from_the_panel_answers_with_the_panel(client, reviewer, make, outbox):
    made = make()
    response = reply(client, made.id, {"body": "On the list now.", "email": ""}, headers={"X-Requested-With": "fetch"})
    page = text_of(response)
    assert response.status_code == 200 and "<html" not in page
    assert "On the list now." in page and "Update sent." in page
    refused = reply(client, made.id, {"body": ""}, headers={"X-Requested-With": "fetch"})
    assert refused.status_code == 400 and "data-panel-feedback" in text_of(refused)


# ---- files ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def two_files(make, db):
    make(files=[ValidFile("shot.png", "image/png", _png()), ValidFile("notes.pdf", "application/pdf", PDF)])
    return {f.filename: f.id for f in db.scalars(select(FeedbackFile))}


def test_a_picture_is_served_inline_and_a_pdf_as_a_download(client, reviewer, two_files):
    picture = client.get(f"/feedback/files/{two_files['shot.png']}")
    assert picture.status_code == 200 and picture.data == _png()
    assert picture.mimetype == "image/png"
    assert picture.headers["X-Content-Type-Options"] == "nosniff"
    assert picture.headers["Content-Disposition"].startswith("inline")
    document = client.get(f"/feedback/files/{two_files['notes.pdf']}")
    assert document.status_code == 200 and document.data == PDF
    assert (
        document.headers["Content-Disposition"].startswith("attachment")
        and "notes.pdf" in document.headers["Content-Disposition"]
    )
    assert document.headers["X-Content-Type-Options"] == "nosniff"


def test_the_sender_may_open_their_files(client, sam, two_files):
    sign_in(client, sam)
    assert client.get(f"/feedback/files/{two_files['shot.png']}").status_code == 200


def test_someone_else_gets_404_for_a_file(client, logged_in_user, two_files):
    assert client.get(f"/feedback/files/{two_files['shot.png']}").status_code == 404
    assert client.get("/feedback/files/999").status_code == 404


def test_files_need_a_signed_in_person(client, two_files):
    assert client.get(f"/feedback/files/{two_files['shot.png']}").status_code in (302, 303)


# ---- the Activity screen -------------------------------------------------------------------------------------------


def test_activity_shows_a_feedback_entry_without_its_content(client, reviewer, make, db, give_set, user_factory):
    made = make(summary="Secret summary", details="Secret details")
    service.reviewer_reply(db, made, reviewer, "question", "Secret question", [])
    db.commit()
    give_set(["view_activity"], user=reviewer)
    page = text_of(client.get("/admin/activity"))
    assert re.search(rf'<a href="{URL}/{made.id}">FB-0001</a>: question sent', page)
    assert "Secret" not in page

    reader = user_factory()
    give_set(["view_activity"], user=reader)
    other = client.application.test_client()
    sign_in(other, reader)
    page = text_of(other.get("/admin/activity"))
    assert "FB-0001" not in page  # feedback entries are for those who manage feedback
    assert "Secret" not in page
