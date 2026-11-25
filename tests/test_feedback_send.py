"""Sending feedback: the link, the form page, the thank-you, the limits and the email to the owner (database)."""

from __future__ import annotations

import io

import pytest
from conftest import post, sign_in
from sqlalchemy import func, select
from test_feedback_service import _png

from tracker.feedback import service
from tracker.mail import smtp
from tracker.models import AppSetting, FeedbackFile, FeedbackMessage, FeedbackRequest

FORM = {"kind": "idea", "summary": "Add a dark chart theme", "details": "", "with_page": "1"}


@pytest.fixture
def sender(client, user_factory):
    user = user_factory(full_name="Sam Taylor", email="sam@example.com")
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
def owner_address(db):
    db.add(AppSetting(key="feedback_email", value="owner-a@example.org, owner-b@example.org"))
    db.commit()


def send(client, data=None, files=None):
    payload = dict(FORM, **(data or {}))
    for key, value in list((files or {}).items()):
        payload[key] = value
    return post(client, "/feedback/new", payload, content_type="multipart/form-data")


def upload(name: str, data: bytes):
    return (io.BytesIO(data), name)


def body(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


# ---- the link ------------------------------------------------------------------------------------------------------


def test_the_link_shows_on_a_signed_in_page_with_the_page_and_its_title(client, sender):
    page = client.get("/").get_data(as_text=True)
    assert "Feedback on this page" in page
    assert "/feedback/new?page=/&amp;title=Trackers" in page
    assert "feedback.js" in page


def test_the_link_is_not_on_the_sign_in_page(client):
    assert "Feedback on this page" not in client.get("/login").get_data(as_text=True)


def test_the_link_is_hidden_and_the_form_refused_when_switched_off(client, sender, db):
    db.add(AppSetting(key="feedback_link", value="0"))
    db.commit()
    assert "Feedback on this page" not in client.get("/").get_data(as_text=True)
    assert client.get("/feedback/new").status_code == 404
    assert send(client).status_code == 404


def test_the_form_needs_a_signed_in_person(client):
    response = client.get("/feedback/new")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_the_form_page_carries_the_copy(client, sender):
    page = client.get("/feedback/new?page=/trackers&title=Trackers").get_data(as_text=True)
    for text in (
        "An idea",
        "Something is wrong",
        "In one line",
        "Tell us more",
        "Optional. A sentence or two is plenty.",
        "Screenshots and files",
        "Up to 5 files, 5 MB each: pictures, PDF, Word, Excel or text.",
        "Send this page with it",
        "Sent as Sam Taylor (sam@example.com) from your account, so the reply comes back to you.",
        "Send feedback",
    ):
        assert text in page
    assert 'enctype="multipart/form-data"' in page


# ---- sending -------------------------------------------------------------------------------------------------------


def test_sending_keeps_the_request_and_shows_the_thank_you(client, sender, db):
    response = send(client, {"page_title": "Core Rollout", "page_url": "/trackers/3", "browser": "Edge on Windows"})
    assert response.status_code == 302
    request = db.scalars(select(FeedbackRequest)).one()
    assert request.sender_id == sender.id and request.kind == "idea" and request.status == "new"
    assert (request.page_title, request.page_url, request.browser) == ("Core Rollout", "/trackers/3", "Edge on Windows")
    assert response.headers["Location"].startswith(f"/feedback/sent/{request.id}")
    page = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Thank you, Sam" in page
    assert "Your idea is with the people who run Progress Tracker" in page
    assert f"Reference {service.reference(request.id)}" in page
    assert "Add a dark chart theme" in page and "Core Rollout" in page
    assert "Send another" in page and "Close" in page


def test_a_problem_report_says_so_on_the_thank_you(client, sender, db):
    response = send(client, {"kind": "problem", "details": "The chart is blank."})
    page = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Your report is with the people who run Progress Tracker" in page


def test_an_unknown_kind_is_kept_as_an_idea(client, sender, db):
    assert send(client, {"kind": "complaint"}).status_code == 302
    assert db.scalars(select(FeedbackRequest)).one().kind == "idea"


@pytest.mark.parametrize("back", ["https://elsewhere.example/x", "//elsewhere.example/x", "javascript:alert(1)"])
def test_the_thank_you_links_back_only_within_the_site(client, sender, db, back):
    created = service.create_request(db, sender, "idea", "Mine", "", "", "", "", [])
    db.commit()
    page = client.get(f"/feedback/sent/{created.id}", query_string={"back": back}).get_data(as_text=True)
    assert "elsewhere" not in page and "javascript" not in page
    assert '<a class="button primary" href="/" data-dialog-close>Close</a>' in page


def test_the_thank_you_links_back_to_the_page_it_came_from(client, sender, db):
    created = service.create_request(db, sender, "idea", "Mine", "", "", "", "", [])
    db.commit()
    page = client.get(f"/feedback/sent/{created.id}", query_string={"back": "/trackers/3"}).get_data(as_text=True)
    assert '<a class="button primary" href="/trackers/3" data-dialog-close>Close</a>' in page


def test_only_the_sender_sees_the_thank_you(client, sender, db, user_factory):
    other = user_factory(is_admin=True)
    created = service.create_request(db, other, "idea", "Mine", "", "", "", "", [])
    db.commit()
    assert client.get(f"/feedback/sent/{created.id}").status_code == 404
    assert client.get("/feedback/sent/999999").status_code == 404
    assert client.get("/feedback/sent/99999999999").status_code == 404


def test_one_line_is_required_and_at_most_150(client, sender, db):
    for summary in ("", "   ", "x" * 151):
        response = send(client, {"summary": summary})
        assert response.status_code == 400
    assert "Keep it to one line, 150 characters at most." in send(client, {"summary": "x" * 151}).get_data(as_text=True)
    assert send(client, {"summary": "x" * 150}).status_code == 302
    assert db.scalar(select(func.count()).select_from(FeedbackRequest)) == 1


def test_a_problem_needs_details_and_details_stop_at_5000(client, sender, db):
    refused = send(client, {"kind": "problem", "details": " "})
    assert refused.status_code == 400 and "Say what happened." in refused.get_data(as_text=True)
    assert send(client, {"details": "y" * 5001}).status_code == 400
    assert send(client, {"details": "y" * 5000}).status_code == 302
    assert send(client, {"kind": "idea", "details": ""}).status_code == 302
    assert db.scalar(select(func.count()).select_from(FeedbackRequest)) == 2


def test_the_form_is_shown_again_with_what_was_typed(client, sender):
    page = send(client, {"summary": "", "details": "Typed details", "kind": "problem"}).get_data(as_text=True)
    assert "Typed details" in page and "What happened?" in page


def test_files_are_kept_with_the_first_message(client, sender, db):
    response = send(client, files={"files": [upload("shot.png", _png()), upload("notes.txt", b"hello")]})
    assert response.status_code == 302
    files = db.scalars(select(FeedbackFile).order_by(FeedbackFile.id)).all()
    assert [f.filename for f in files] == ["shot.png", "notes.txt"]
    first = db.scalars(select(FeedbackMessage).order_by(FeedbackMessage.id)).first()
    assert {f.message_id for f in files} == {first.id}


@pytest.mark.parametrize(
    "files, message",
    [
        ([upload(f"f{n}.txt", b"a") for n in range(6)], "Attach at most 5 files."),
        ([upload("big.txt", b"a" * (5 * 1024 * 1024 + 1))], "big.txt is over 5 MB."),
        ([upload("page.png", b"<html><body>x</body></html>")], "page.png is not a picture, PDF, Word, Excel or text"),
    ],
)
def test_files_that_are_refused_save_nothing(client, sender, db, files, message):
    response = send(client, files={"files": files})
    assert response.status_code == 400 and message in response.get_data(as_text=True)
    assert db.scalar(select(func.count()).select_from(FeedbackRequest)) == 0
    assert db.scalar(select(func.count()).select_from(FeedbackFile)) == 0


def test_unticking_send_this_page_stores_no_page_or_browser(client, sender, db):
    data = {"page_title": "Core", "page_url": "/trackers/3", "browser": "Edge on Windows"}
    response = post(client, "/feedback/new", dict(FORM, **data) | {"with_page": ""}, content_type="multipart/form-data")
    assert response.status_code == 302
    request = db.scalars(select(FeedbackRequest)).one()
    assert (request.page_title, request.page_url, request.browser) == ("", "", "")


def test_a_page_address_that_leaves_the_site_is_not_kept(client, sender, db):
    send(client, {"page_url": "https://elsewhere.example/x", "page_title": "T"})
    assert db.scalars(select(FeedbackRequest)).one().page_url == ""


def test_the_browser_is_read_from_the_request_when_the_page_sent_none(client, sender, db):
    agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36 Edg/120.0"
    payload = {k: v for k, v in dict(FORM).items()}
    post(client, "/feedback/new", payload, content_type="multipart/form-data", headers={"User-Agent": agent})
    assert db.scalars(select(FeedbackRequest)).one().browser == "Edge on Windows"


# ---- the body limit ------------------------------------------------------------------------------------------------


def test_a_27_mb_body_is_refused_and_a_5_file_body_is_taken(client, sender, db):
    huge = [upload(f"{n}.txt", b"a" * (5 * 1024 * 1024)) for n in range(5)] + [upload("b.txt", b"a" * 2 * 1024 * 1024)]
    assert send(client, files={"files": huge}).status_code == 413
    assert db.scalar(select(func.count()).select_from(FeedbackRequest)) == 0
    five = [upload(f"{n}.txt", b"a" * (5 * 1024 * 1024)) for n in range(5)]
    assert send(client, files={"files": five}).status_code == 302


def test_other_routes_keep_the_1_mb_limit(client, sender):
    response = post(client, "/logout", {"filler": "a" * (1024 * 1024 + 10)})
    assert response.status_code == 413


# ---- the email to the owner ----------------------------------------------------------------------------------------


def test_the_owner_gets_one_email_from_the_sender(client, sender, db, outbox, mail_on, owner_address):
    send(
        client,
        {"details": "More on it.", "page_title": "Core Rollout", "page_url": "/trackers/3", "browser": "Edge"},
        files={"files": [upload("shot.png", _png())]},
    )
    request = db.scalars(select(FeedbackRequest)).one()
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg["To"] == "owner-a@example.org, owner-b@example.org"
    assert msg["Reply-To"] == "sam@example.com"
    assert msg["Subject"] == "Idea from Sam Taylor: Add a dark chart theme"
    page = body(msg)
    assert service.reference(request.id) in page and "More on it." in page
    assert "Core Rollout" in page and "Edge" in page
    assert "Reply to this email to answer Sam Taylor directly." in page
    assert "Open in Progress Tracker" in page
    assert [a.get_filename() for a in msg.iter_attachments() if a.get_filename()] == ["shot.png"]
    assert request.email_note == ""


def test_a_problem_subject_says_problem(client, sender, outbox, mail_on, owner_address):
    send(client, {"kind": "problem", "details": "It broke."})
    assert outbox[0]["Subject"] == "Problem from Sam Taylor: Add a dark chart theme"


def test_files_over_10_mb_together_are_listed_not_attached(client, sender, db, outbox, mail_on, owner_address):
    files = [upload(f"part{n}.txt", b"a" * (4 * 1024 * 1024)) for n in range(3)]
    send(client, files={"files": files})
    msg = outbox[0]
    assert [a for a in msg.iter_attachments() if a.get_filename()] == []
    page = body(msg)
    assert "part0.txt" in page and "part2.txt" in page and "in the request" in page


def test_no_address_keeps_the_request_and_says_why(client, sender, db, outbox, mail_on):
    assert send(client).status_code == 302
    request = db.scalars(select(FeedbackRequest)).one()
    assert request.email_note == "Email not sent: no feedback address set"
    assert outbox == []
    note = db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "email")).one()
    assert (note.role, note.body) == ("system", request.email_note)


def test_no_mail_setup_keeps_the_request_and_says_why(client, sender, db, outbox, owner_address):
    send(client)
    assert db.scalars(select(FeedbackRequest)).one().email_note == "Email not sent: email is not set up"
    assert outbox == []


def test_a_refused_send_keeps_the_request_and_says_why(client, sender, db, mail_on, owner_address, monkeypatch):
    def refuse(msg):
        raise smtp.MailError("550 no")

    monkeypatch.setattr(smtp, "send_message", refuse)
    assert send(client).status_code == 302
    request = db.scalars(select(FeedbackRequest)).one()
    assert request.email_note == "Email not sent: the mail server refused it"
    assert db.scalars(select(FeedbackMessage).where(FeedbackMessage.kind == "email")).one().body == request.email_note
