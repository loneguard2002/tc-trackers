"""The email to administrators when a failed sign-in starts a block: who gets it, at most one every 15 minutes, and
never in the way of the sign-in that set it off."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from conftest import post
from sqlalchemy import select

from tracker.mail import sign_in_alerts, smtp
from tracker.models import AppSetting, AuditLog


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
def admins(user_factory):
    return [
        user_factory(email="admin1@example.com", is_admin=True),
        user_factory(email="admin2@example.com", is_admin=True),
    ]


def _lock_out(client, email: str, times: int = 5) -> None:
    for _ in range(times):
        post(client, "/login", {"email": email, "password": "wrong-password"})


def _html(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


def _setting(db, key: str) -> str | None:
    return db.scalar(select(AppSetting.value).where(AppSetting.key == key))


def test_a_block_emails_every_active_administrator(client, db, user_factory, admins, outbox, mail_on):
    user_factory(email="retired@example.com", is_admin=True, status="disabled")
    user_factory(email="someone@example.com")
    _lock_out(client, "locked@example.com")
    (msg,) = outbox
    assert msg["Bcc"] == "admin1@example.com, admin2@example.com"
    assert msg["Subject"] == "Progress Tracker: sign-in blocked for 1 account or address"
    body = _html(msg)
    assert "locked@example.com" in body and "5 in 5 min" in body and "/admin/sign-in-protection" in body
    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "sign_in_alert_sent"))
    assert entry.detail == {"blocked": 1, "recipients": ["admin1@example.com", "admin2@example.com"]}


def test_holders_of_the_permission_are_emailed_too(client, db, user_factory, admins, give_set, outbox, mail_on):
    guard = user_factory(email="guard@example.com")
    give_set(["manage_sign_in_protection"], user=guard)
    _lock_out(client, "locked@example.com")
    (msg,) = outbox
    assert msg["Bcc"] == "admin1@example.com, admin2@example.com, guard@example.com"


def test_failures_below_the_limit_email_nobody(client, db, admins, outbox, mail_on):
    _lock_out(client, "typo@example.com", times=4)
    assert outbox == []


def test_one_email_at_most_every_15_minutes(client, db, admins, outbox, mail_on):
    _lock_out(client, "first@example.com")
    _lock_out(client, "second@example.com")
    assert len(outbox) == 1
    blocks = db.scalars(select(AuditLog).where(AuditLog.action == "sign_in_blocked")).all()
    assert len(blocks) == 2  # the second block is not emailed, but the menu still counts it


def test_after_15_minutes_the_next_block_is_emailed_with_everyone_blocked(client, db, admins, outbox, mail_on):
    _lock_out(client, "first@example.com")
    earlier = datetime.fromisoformat(_setting(db, sign_in_alerts.LAST_ALERT_KEY)) - timedelta(minutes=16)
    db.merge(AppSetting(key=sign_in_alerts.LAST_ALERT_KEY, value=earlier.isoformat()))
    db.commit()
    _lock_out(client, "second@example.com")
    assert len(outbox) == 2
    body = _html(outbox[1])
    assert "first@example.com" in body and "second@example.com" in body
    assert outbox[1]["Subject"] == "Progress Tracker: sign-in blocked for 2 accounts or addresses"


def test_no_email_when_the_administrators_switched_it_off(client, db, admins, outbox, mail_on):
    db.add(AppSetting(key="login_block_email", value="off"))
    db.commit()
    _lock_out(client, "locked@example.com")
    assert outbox == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == "sign_in_blocked")).first() is not None  # still counted


def test_no_email_without_a_mail_server(client, db, admins, outbox):
    _lock_out(client, "locked@example.com")
    assert outbox == []


def test_a_failed_delivery_gives_the_gap_back_and_sign_in_goes_on(client, db, admins, monkeypatch, mail_on):
    def fail(msg):
        raise smtp.MailError("The mail server refused the connection.")

    monkeypatch.setattr(smtp, "send_message", fail)
    response = None
    for _ in range(5):
        response = post(client, "/login", {"email": "locked@example.com", "password": "wrong-password"})
    assert response.status_code == 200 and "Invalid email or password." in response.get_data(as_text=True)
    assert _setting(db, sign_in_alerts.LAST_ALERT_KEY) is None  # the next block may email
    assert db.scalars(select(AuditLog).where(AuditLog.action == "sign_in_alert_sent")).first() is None
