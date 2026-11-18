"""Access requests (design 2026-11-18): who is emailed on a first Microsoft sign-in, on approval and on turning
down, the turned-down state, the daily reminder, its settings and the count beside Users (database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import TENANT, post, sign_in
from sqlalchemy import select
from test_sso import FakeMsal, callback, claims, location, start

from tracker.mail import access, smtp
from tracker.models import AppSetting, AuditLog, User


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


def html(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


def actions(db, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def test_first_sign_in_emails_the_approvers_and_the_person(sso_client, monkeypatch, db, user_factory, outbox, mail_on):
    admin = user_factory(is_admin=True, email="boss@example.com")
    user_factory(email="viewer@example.com")  # holds no manage_users: not an approver
    start(sso_client, monkeypatch, FakeMsal(claims(name="Sam Taylor", email="sam@example.com")))
    response = callback(sso_client)
    assert location(response).endswith("/auth/pending")
    to_team, to_person = outbox
    assert to_team["Subject"] == "Progress Tracker: Sam Taylor is asking for access"
    assert to_team["Bcc"] == admin.email
    assert "Review access requests" in html(to_team) and "/admin/users" in html(to_team)
    assert "Do not approve it, and tell the Infosec team:" in html(to_team)
    assert to_person["Subject"] == "Progress Tracker: we have your access request"
    assert to_person["To"] == "sam@example.com"
    assert "Did not sign in yourself? Tell the Infosec team:" in html(to_person)
    assert [entry.detail["email"] for entry in actions(db, "access_email_sent")] == [
        "request_approvers",
        "request_person",
    ]
    page = sso_client.get("/auth/pending").get_data(as_text=True)
    assert "Thanks, Sam. Your access request has been sent." in page
    assert "We have emailed the team who approve access." in page and "sam@example.com" in page


def test_emails_carry_the_logo_inline_for_outlook(sso_client, monkeypatch, db, user_factory, outbox, mail_on):
    user_factory(is_admin=True)
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    for msg in outbox:
        logo = [part for part in msg.walk() if part.get_content_type() == "image/jpeg"]
        assert [part["Content-ID"] for part in logo] == ["<tradition-logo>"]
        assert 'src="cid:tradition-logo"' in html(msg) and 'width="150" height="28" alt="Tradition"' in html(msg)
        assert msg.get_body(preferencelist=("plain",)) is not None


def test_without_a_mail_server_nobody_is_emailed_and_the_page_says_so(
    sso_client, monkeypatch, db, user_factory, outbox
):
    user_factory(is_admin=True)
    start(sso_client, monkeypatch, FakeMsal(claims()))
    callback(sso_client)
    assert outbox == []
    page = sso_client.get("/auth/pending").get_data(as_text=True)
    assert "will see it when they next open Progress Tracker" in page


def test_a_waiting_person_signing_in_again_emails_nobody(sso_client, monkeypatch, db, user_factory, outbox, mail_on):
    user_factory(is_admin=True)
    user_factory(auth_source="sso", password_hash=None, sso_subject=f"{TENANT}:oid-1", status="pending")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    assert location(callback(sso_client)).endswith("/auth/pending")
    assert outbox == []


def test_the_pending_page_without_a_sign_in_goes_back_to_sign_in(client):
    assert location(client.get("/auth/pending")).endswith("/login")
    assert location(client.get("/auth/declined")).endswith("/login")


def test_turning_down_emails_the_person_and_keeps_their_microsoft_link(client, db, user_factory, outbox, mail_on):
    admin = user_factory(is_admin=True)
    sam = user_factory(
        full_name="Sam Taylor", auth_source="sso", password_hash=None, sso_subject="s-1", status="pending"
    )
    sign_in(client, admin)
    response = post(client, f"/admin/users/{sam.id}/decline")
    assert location(response).endswith("/admin/users")
    db.refresh(sam)
    assert sam.status == "declined" and sam.sso_subject == "s-1"
    (entry,) = actions(db, "user_declined")
    assert entry.user_id == admin.id and entry.target_user_id == sam.id
    (msg,) = outbox
    assert msg["Subject"] == "Progress Tracker: sorry, your access request was not approved"
    assert "We are sorry, but your request for access" in html(msg) and admin.full_name not in html(msg)
    page = client.get("/admin/users").get_data(as_text=True)
    assert "Turned down" in page and f"by {admin.full_name}" in page


def test_only_a_waiting_person_can_be_turned_down(client, db, user_factory):
    sign_in(client, user_factory(is_admin=True))
    assert post(client, f"/admin/users/{user_factory().id}/decline").status_code == 400


def test_turning_down_needs_manage_users(client, db, user_factory):
    sign_in(client, user_factory())
    waiting = user_factory(status="pending", auth_source="sso", password_hash=None)
    assert post(client, f"/admin/users/{waiting.id}/decline").status_code == 403


def test_a_turned_down_person_sees_the_message_and_nobody_is_emailed(sso_client, monkeypatch, db, user_factory, outbox,
                                                                     mail_on):  # fmt: skip
    user_factory(is_admin=True)
    person = user_factory(auth_source="sso", password_hash=None, sso_subject=f"{TENANT}:oid-1", status="declined")
    start(sso_client, monkeypatch, FakeMsal(claims()))
    assert location(callback(sso_client)).endswith("/auth/declined")
    assert outbox == []
    assert [entry.target_user_id for entry in actions(db, "sso_declined_attempt")] == [person.id]
    with sso_client.session_transaction() as sess:
        assert "user_id" not in sess
    page = sso_client.get("/auth/declined").get_data(as_text=True)
    assert "Sorry, your access to Progress Tracker was not approved" in page
    assert "Signing in again does not send a new request." in page and access.DEFAULT_INFOSEC in page


def test_a_turned_down_person_can_still_be_approved(client, db, user_factory, outbox, mail_on):
    admin = user_factory(is_admin=True)
    person = user_factory(auth_source="sso", password_hash=None, status="declined")
    sign_in(client, admin)
    post(client, f"/admin/users/{person.id}/approve")
    db.refresh(person)
    assert person.status == "active"
    assert actions(db, "user_approved")[0].detail == {"before": "declined", "after": "active"}
    (msg,) = outbox
    assert msg["Subject"] == "Progress Tracker: your access is approved"
    assert "The team has approved your access to Progress Tracker." in html(msg) and admin.full_name not in html(msg)
    assert "Open Progress Tracker" in html(msg)


def test_users_menu_counts_the_waiting_requests(client, db, user_factory):
    sign_in(client, user_factory(is_admin=True))
    user_factory(status="pending", auth_source="sso", password_hash=None)
    page = client.get("/admin/users").get_data(as_text=True)
    assert '<span class="nav-count" title="waiting for approval">1<' in page


def _waiting_since(user_factory, db, days: int) -> User:
    person = user_factory(status="pending", auth_source="sso", password_hash=None)
    person.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()
    return person


def test_reminder_lists_old_requests_once_a_day(db, user_factory, outbox, mail_on, app):
    admin = user_factory(is_admin=True)
    old = _waiting_since(user_factory, db, 4)
    _waiting_since(user_factory, db, 1)  # younger than the 3-day setting
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        assert access.send_due_reminder(db, now) is True
        assert access.send_due_reminder(db, now) is False  # today's is claimed
    (msg,) = outbox
    assert msg["Subject"] == "Progress Tracker: 1 access request waiting"
    assert msg["Bcc"] == admin.email and old.email in html(msg)
    assert actions(db, "access_reminder_sent")[0].detail["waiting"] == 1


def test_reminder_off_at_zero_days(db, user_factory, outbox, mail_on, app):
    user_factory(is_admin=True)
    _waiting_since(user_factory, db, 10)
    db.add(AppSetting(key=access.REMINDER_DAYS_KEY, value="0"))
    db.commit()
    with app.test_request_context():
        assert access.send_due_reminder(db, datetime.now(timezone.utc)) is False
    assert outbox == []


def test_a_failed_reminder_gives_the_day_back(db, user_factory, monkeypatch, mail_on, app):
    user_factory(is_admin=True)
    _waiting_since(user_factory, db, 5)

    def fail(msg):
        raise smtp.MailError("down")

    monkeypatch.setattr(smtp, "send_message", fail)
    with app.test_request_context(), pytest.raises(smtp.MailError):
        access.send_due_reminder(db, datetime.now(timezone.utc))
    assert db.scalar(select(AppSetting).where(AppSetting.key == access.LAST_REMINDER_KEY)) is None


def test_email_settings_keep_the_infosec_address_and_reminder_days(client, db, user_factory):
    sign_in(client, user_factory(is_admin=True))
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert f'value="{access.DEFAULT_INFOSEC}"' in page and 'id="access_reminder_days"' in page
    response = post(client, "/admin/smtp", {"access_infosec_email": "Security@Example.com", "access_reminder_days": "5",
                                            "report_email_subject": "{{summary}}", "smtp_auth": "none"})  # fmt: skip
    assert response.status_code == 302
    assert access.infosec_email(db) == "security@example.com" and access.reminder_days(db) == 5
    changed = actions(db, "smtp_settings_updated")[-1].detail["changed"]
    assert access.INFOSEC_KEY in changed and access.REMINDER_DAYS_KEY in changed


@pytest.mark.parametrize("field, value", [("access_infosec_email", "not an address"), ("access_reminder_days", "91"),
                                          ("access_reminder_days", "-1"), ("access_reminder_days", "")])  # fmt: skip
def test_email_settings_refuse_bad_access_values(client, db, user_factory, field, value):
    sign_in(client, user_factory(is_admin=True))
    assert (
        post(
            client, "/admin/smtp", {field: value, "report_email_subject": "{{summary}}", "smtp_auth": "none"}
        ).status_code
        == 400
    )
