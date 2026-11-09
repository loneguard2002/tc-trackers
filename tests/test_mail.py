"""Report email: pure composition and SMTP tests run without a database; sending and route tests need one."""

from __future__ import annotations

import dataclasses
import html
import re
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
from conftest import post, sign_in
from report_helpers import synthetic_report

from tracker.mail import compose, sending, smtp
from tracker.mail.compose import (
    DEFAULT_BODY,
    DEFAULT_SUBJECT,
    PLACEHOLDERS,
    build_report_email,
    email_summary,
    normalise_recipient,
    placeholder_context,
    render_placeholders,
    render_subject,
    report_subject,
    sanitise_subject,
    unknown_placeholders,
)
from tracker.models import AppSetting, AuditLog, EmailTemplate, Recipient, ReportSend

LINK = "http://localhost:5000/trackers/1/report?week=2026-09-11"
NOW = datetime(2026, 9, 11, 17, 0, tzinfo=timezone.utc)


def email_for(app, recipients=("a@example.com",), template=None, report=None, sender="reports@example.com"):
    report = report or synthetic_report()[0]
    with app.test_request_context("/"):
        return build_report_email(report, template, list(recipients), LINK, b"%PDF-fake", sender=sender)


# --- Pure: placeholders -------------------------------------------------------------------------------------


def test_render_placeholders_escapes_html():
    assert render_placeholders("{{headline}}", {"headline": "<b>"}) == "&lt;b&gt;"


def test_unknown_placeholder_left_in_place():
    assert render_placeholders("{{nope}}", {}) == "{{nope}}"


def test_placeholder_spacing_tolerated():
    assert render_placeholders("{{ status }}", {"status": "Red"}) == "Red"


def test_unknown_placeholders_listed():
    assert unknown_placeholders("{{status}} {{nope}}", "{{other}} {{nope}}") == ["nope", "other"]
    assert unknown_placeholders(DEFAULT_SUBJECT, DEFAULT_BODY) == []


def test_default_templates_use_only_known_placeholders():
    assert set(PLACEHOLDERS) >= set(compose._PLACEHOLDER_RE.findall(DEFAULT_SUBJECT + DEFAULT_BODY))
    assert "figures" in DEFAULT_BODY and "needed_from_you" in DEFAULT_BODY and "this_week" in DEFAULT_BODY


def test_placeholder_context_formats_values():
    report, _ = synthetic_report()
    report.inputs = SimpleNamespace(status="Amber", headline="Going well", decisions="")
    context = placeholder_context(report, LINK)
    assert set(context) == set(PLACEHOLDERS)
    assert context["week_ending"] == "11 Sep 2026"
    assert context["status"] == "Amber" and context["headline"] == "Going well"
    assert context["percent_complete"].endswith("%")
    assert context["decisions"] == "None"
    assert context["tracker_name"] == "Stub tracker"
    assert context["report_link"] == LINK


def test_placeholder_context_missing_values_are_dashes():
    report, _ = synthetic_report()
    context = placeholder_context(report, LINK)
    assert context["status"] == "–" and context["headline"] == "–"


# --- Pure: subject ------------------------------------------------------------------------------------------


def test_subject_strips_crlf_and_cannot_inject_header(app):
    report, _ = synthetic_report()
    report.inputs = SimpleNamespace(status="Red", headline="x\r\nBcc: x@y", decisions="")
    subject = render_subject("{{headline}}", placeholder_context(report, LINK))
    assert "\r" not in subject and "\n" not in subject
    msg = email_for(app, report=report, template=SimpleNamespace(subject="{{headline}}", body_html="<p>x</p>"))
    assert msg["Bcc"] == "a@example.com"
    assert msg.get_all("Bcc") == ["a@example.com"]
    assert "x@y" not in msg["Bcc"]


def test_subject_entity_cannot_smuggle_newline():
    assert "\n" not in sanitise_subject("a&#10;b") and "\r" not in sanitise_subject("a&#13;b")


def test_subject_decodes_entities_for_plain_text():
    assert render_subject("{{headline}}", {"headline": "A & B"}) == "A & B"


def test_default_subject_renders():
    report, _ = synthetic_report()
    assert render_subject(DEFAULT_SUBJECT, placeholder_context(report, LINK)).startswith("Stub tracker | ")


# --- Pure: the summary line ------------------------------------------------------------------------------------


def summary_for(**changes):
    report, _ = synthetic_report()
    report.inputs = SimpleNamespace(status="Green", headline="", decisions="")
    values = {
        "completed": 25,
        "total_scope": 180,
        "remaining": 155,
        "pct_complete": 25 / 180,
        "this_week_actual": 5,
        "this_week_target": 3,
    }
    report.headline = dataclasses.replace(report.headline, **(values | changes))
    report.tracker.name = "Network refresh"
    report.week_ending = date(2026, 11, 6)
    report.open_risks, report.new_risk_rags = 3, ["Red"]
    return report


def test_summary_matches_the_agreed_line():
    assert email_summary(summary_for()) == (
        "Network refresh | 06/11/26 : Green | 25 (+5 v +3) of 180 devices done (14%) | 155 left | 3 risks (1 new - red)"
    )


@pytest.mark.parametrize(
    "changes, part",
    [
        ({"this_week_target": None}, "| 25 (+5) of 180 devices done (14%) |"),
        ({"this_week_actual": 0}, "| 25 (+0 v +3) of 180 devices"),
        ({"this_week_actual": None}, "| 25 (+0 v +3) of 180 devices"),  # a week with no row yet
        (
            {"completed": 1170, "total_scope": 2400, "remaining": 1230, "pct_complete": 1170 / 2400},
            "| 1,170 (+5 v +3) of 2,400 devices done (49%) | 1,230 left |",
        ),
    ],
)
def test_summary_progress_cases(changes, part):
    assert part in email_summary(summary_for(**changes))


@pytest.mark.parametrize(
    "open_risks, rags, ending",
    [
        (3, [], "| 3 risks"),
        (1, [], "| 1 risk"),
        (0, [], "| 0 risks"),
        (3, ["Red", "Amber"], "| 3 risks (2 new - 1 red, 1 amber)"),
        (4, ["Red", "Red"], "| 4 risks (2 new - 2 red)"),
        (2, [None], "| 2 risks (1 new)"),
        (2, ["Red", None], "| 2 risks (2 new - 1 red)"),
    ],
)
def test_summary_risk_cases(open_risks, rags, ending):
    report = summary_for()
    report.open_risks, report.new_risk_rags = open_risks, rags
    line = email_summary(report)
    assert line.endswith(ending) and "()" not in line


def test_summary_without_a_unit_has_no_double_space():
    report = summary_for()
    report.tracker.unit_label = ""
    assert "| 25 (+5 v +3) of 180 done (14%) |" in email_summary(report)


def test_summary_without_a_status_says_so():
    report = summary_for()
    report.inputs = None
    assert " | 06/11/26 : No status | " in email_summary(report)


def test_summary_is_a_known_placeholder_and_the_default_subject():
    assert DEFAULT_SUBJECT == "{{summary}}" and "summary" in PLACEHOLDERS
    assert placeholder_context(summary_for(), LINK)["summary"].startswith("Network refresh | 06/11/26")


# --- Pure: recipient validation -----------------------------------------------------------------------------


@pytest.mark.parametrize("raw",
    [
        "", "  ", "a", "a@", "@b.com", "a@@b.com", "a b@c.com", "a@b c.com", "a@b", "x,y@corp.com", "x;y@corp.com",
        "<a@b.com>", '"a"@b.com', "a@b..com", "a@.b.com", "a@b.com.", "a@b.com,c@d.com", "a@b_c.com", "a\r\n@b.com",
    ],
)  # fmt: skip
def test_recipient_rejected(raw):
    assert normalise_recipient(raw)[1] is not None


@pytest.mark.parametrize("raw", ["a@b.com", "first.last+tag@sub.example.co.uk", "o'brien@example.com", "a_b%c@x-y.org"])
def test_recipient_accepted(raw):
    assert normalise_recipient(raw) == (raw, None)


def test_recipient_normalised():
    assert normalise_recipient("  Ann@Example.COM ") == ("ann@example.com", None)


# --- Pure: the message --------------------------------------------------------------------------------------


def test_email_has_inline_chart_and_pdf(app):
    msg = email_for(app)
    parts = list(msg.walk())
    chart = [p for p in parts if p.get("Content-ID") == "<remaining-chart>"]
    assert chart and chart[0].get_content_type() == "image/png"
    assert chart[0].get_payload(decode=True).startswith(b"\x89PNG")
    assert any(p.get_filename() and p.get_filename().endswith(".pdf") for p in parts)
    assert msg["Bcc"] and "a@example.com" in msg["Bcc"]
    assert msg["To"] == "reports@example.com" == msg["From"]


def test_email_html_references_chart_by_cid_and_links_report(app):
    msg = email_for(app)
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "cid:remaining-chart" in html and LINK in html and "View the full report" in html
    assert "data:image" not in html


def test_email_has_plain_text_alternative(app):
    msg = email_for(app)
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Next week's target 10 devices" in text and LINK in text and "<" not in text


def test_email_escapes_untrusted_values_in_body(app):
    report, _ = synthetic_report()
    report.inputs = SimpleNamespace(status="Red", headline="<script>alert(1)</script>", decisions="")
    html = email_for(app, report=report).get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_email_uses_custom_template(app):
    template = SimpleNamespace(subject="Custom {{status}}", body_html="<p>Hello {{tracker_name}}</p>")
    msg = email_for(app, template=template)
    assert msg["Subject"] == "Custom –"
    assert "Hello Stub tracker" in msg.get_body(preferencelist=("html",)).get_content()


def test_email_multiple_recipients_in_bcc(app):
    assert email_for(app, recipients=("a@example.com", "b@example.com"))["Bcc"] == "a@example.com, b@example.com"


# --- Pure: backoff ------------------------------------------------------------------------------------------


def test_backoff_schedule():
    assert [sending.next_attempt_delay(n) for n in (1, 2, 3, 4)] == [timedelta(minutes=m) for m in (5, 15, 60, 240)]
    assert sending.BACKOFF_MINUTES == [5, 15, 60, 240]
    assert sending.next_attempt_delay(5) is None and sending.next_attempt_delay(9) is None


# --- Pure: SMTP ---------------------------------------------------------------------------------------------


class FakeServer:
    instances: list = []
    features = {"starttls": ""}
    fail_send: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.esmtp_features = dict(self.features)
        self.calls: list = []
        self.sent = None
        FakeServer.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def docmd(self, *args):
        self.calls.append(("docmd", *args))
        return 235, b"ok"

    def send_message(self, msg):
        if self.fail_send:
            raise self.fail_send
        self.sent = msg

    def quit(self):
        raise smtplib.SMTPServerDisconnected("grumpy")

    def close(self):
        pass


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeServer.instances = []
    FakeServer.features = {"starttls": ""}
    FakeServer.fail_send = None
    monkeypatch.setattr(smtplib, "SMTP", FakeServer)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeServer)
    return FakeServer


def cfg(**overrides):
    values = {
        "smtp_host": "mail.example.com", "smtp_port": "587", "smtp_auth": "plain", "smtp_user": "u@example.com",
        "smtp_from": "reports@example.com",
    }  # fmt: skip
    values.update(overrides)
    return smtp.build_config(values, {"SMTP_PASSWORD": "s3cret"})


def simple_message():
    msg = EmailMessage()
    msg["Subject"] = "s"
    msg["Bcc"] = "a@example.com"
    msg.set_content("x")
    return msg


def test_config_reads_settings_and_env_secrets():
    config = cfg(smtp_port="")
    assert config["port"] == 587 and config["password"] == "s3cret" and config["from_"] == "reports@example.com"
    assert smtp.build_config({"smtp_user": "u@x.com"}, {})["from_"] == "u@x.com"


def test_deliver_plain_uses_timeout_starttls_and_login(fake_smtp):
    msg = simple_message()
    smtp.deliver(msg, cfg())
    server = fake_smtp.instances[0]
    assert server.timeout == 30
    assert "starttls" in server.calls and ("login", "u@example.com", "s3cret") in server.calls
    assert server.sent["From"] == "reports@example.com" == server.sent["To"]  # QUIT failure did not matter


def test_deliver_refuses_credentials_without_encryption(fake_smtp):
    fake_smtp.features = {}
    with pytest.raises(smtp.MailError, match="unencrypted"):
        smtp.deliver(simple_message(), cfg())
    assert not any(isinstance(c, tuple) and c[0] == "login" for c in fake_smtp.instances[0].calls)


def test_deliver_anonymous_relay_without_tls(fake_smtp):
    fake_smtp.features = {}
    smtp.deliver(simple_message(), cfg(smtp_auth="none"))
    assert fake_smtp.instances[0].sent is not None


def test_deliver_port_465_uses_ssl(monkeypatch, fake_smtp):
    used = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: used.append(k) or FakeServer(*a, **k))
    smtp.deliver(simple_message(), cfg(smtp_port="465"))
    assert used and used[0]["timeout"] == 30


def test_deliver_xoauth2(monkeypatch, fake_smtp):
    monkeypatch.setattr(smtp, "get_oauth2_token", lambda *a: "tok")
    smtp.deliver(simple_message(), cfg(smtp_auth="xoauth2"))
    call = [c for c in fake_smtp.instances[0].calls if isinstance(c, tuple) and c[0] == "docmd"][0]
    assert call[1] == "AUTH" and call[2] == "XOAUTH2 " + smtp.xoauth2_string("u@example.com", "tok")


def test_xoauth2_string_format():
    import base64

    assert base64.b64decode(smtp.xoauth2_string("u", "t")) == b"user=u\x01auth=Bearer t\x01\x01"


def test_deliver_wraps_errors_without_secrets(fake_smtp):
    fake_smtp.fail_send = smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")})
    with pytest.raises(smtp.MailError) as info:
        smtp.deliver(simple_message(), cfg())
    assert "s3cret" not in str(info.value) and isinstance(info.value.__cause__, smtplib.SMTPRecipientsRefused)


def test_deliver_requires_host_and_sender():
    with pytest.raises(smtp.MailError, match="host"):
        smtp.deliver(simple_message(), cfg(smtp_host=""))
    with pytest.raises(smtp.MailError, match="sender"):
        smtp.deliver(simple_message(), cfg(smtp_from="", smtp_user=""))


# --- Pure: the report's "today" -------------------------------------------------------------------------------


def test_scheduled_send_uses_the_local_date_of_the_fire():
    late_utc = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)  # already Saturday 12 September in Sydney
    assert sending.report_today("scheduled", "Australia/Sydney", late_utc) == date(2026, 9, 12)
    assert sending.report_today("scheduled", "Europe/London", late_utc) == date(2026, 9, 12)  # 00:30 BST
    early_utc = datetime(2026, 9, 12, 0, 30, tzinfo=timezone.utc)
    assert sending.report_today("scheduled", "America/New_York", early_utc) == date(2026, 9, 11)


def test_manual_send_keeps_the_application_today(monkeypatch):
    monkeypatch.setattr("tracker.report.views.today", lambda: date(2026, 1, 2))
    now = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
    assert sending.report_today("manual", "Australia/Sydney", now) == date(2026, 1, 2)


# --- Database: sending ---------------------------------------------------------------------------------------


@pytest.fixture
def sent_messages(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    monkeypatch.setattr(sending, "html_to_pdf", lambda html: b"%PDF-fake")
    return sent


@pytest.fixture
def failing_mail(monkeypatch):
    def fail(msg):
        raise smtp.MailError("connection refused")

    monkeypatch.setattr(smtp, "send_message", fail)
    monkeypatch.setattr(sending, "html_to_pdf", lambda html: b"%PDF-fake")


@pytest.fixture
def tracker_with_recipient(app, db, tracker_factory):
    tracker = tracker_factory()
    db.add(Recipient(tracker_id=tracker.id, email="a@example.com"))
    db.commit()
    return tracker


WEEK = date(2026, 9, 11)


def test_send_report_success_records_send(app, db, tracker_with_recipient, sent_messages):
    with app.app_context():
        send = sending.send_report(db, tracker_with_recipient, WEEK, "manual", None, NOW)
    assert send.status == "sent" and send.recipients == ["a@example.com"] and send.pdf == b"%PDF-fake"
    assert send.sent_at == NOW and send.attempts == 0
    assert len(sent_messages) == 1 and sent_messages[0]["Bcc"] == "a@example.com"
    audit = db.query(AuditLog).filter_by(action="report_sent").one()
    assert audit.detail["recipients"] == ["a@example.com"] and audit.detail["trigger"] == "manual"


def test_send_report_failure_queues_with_backoff(app, db, tracker_with_recipient, failing_mail):
    with app.app_context():
        send = sending.send_report(db, tracker_with_recipient, WEEK, "manual", None, NOW)
    assert (send.status, send.attempts) == ("queued", 1)
    assert send.next_attempt_at == NOW + timedelta(minutes=5)
    assert "MailError" in send.error and "connection refused" in send.error
    assert db.query(AuditLog).filter_by(action="report_send_queued").count() == 1


def test_retry_queued_resends_and_fails_after_4_retries(app, db, tracker_with_recipient, failing_mail, monkeypatch):
    with app.app_context():
        send = sending.send_report(db, tracker_with_recipient, WEEK, "manual", None, NOW)
        assert sending.retry_queued(db, NOW + timedelta(minutes=4)) == 0  # not yet due
        expected = [(2, 15), (3, 60), (4, 240)]
        later = NOW
        for attempts, minutes in expected:
            later = send.next_attempt_at
            assert sending.retry_queued(db, later) == 1
            db.refresh(send)
            assert (send.status, send.attempts) == ("queued", attempts)
            assert send.next_attempt_at == later + timedelta(minutes=minutes)
        assert sending.retry_queued(db, send.next_attempt_at) == 1
        db.refresh(send)
        assert (send.status, send.attempts, send.next_attempt_at) == ("failed", 5, None)
        assert sending.retry_queued(db, NOW + timedelta(days=2)) == 0
    assert db.query(AuditLog).filter_by(action="report_send_failed").count() == 1


def test_retry_queued_success_reuses_stored_pdf(app, db, tracker_with_recipient, failing_mail, monkeypatch):
    with app.app_context():
        send = sending.send_report(db, tracker_with_recipient, WEEK, "manual", None, NOW)
        sent: list = []
        monkeypatch.setattr(smtp, "send_message", sent.append)
        monkeypatch.setattr(sending, "html_to_pdf", lambda html: pytest.fail("PDF must not be regenerated"))
        assert sending.retry_queued(db, send.next_attempt_at) == 1
        db.refresh(send)
    assert send.status == "sent" and send.error is None and send.next_attempt_at is None
    pdf = [p for p in sent[0].walk() if p.get_filename()][0]
    assert pdf.get_payload(decode=True) == b"%PDF-fake"


def test_send_without_recipients_rejected(app, db, tracker_factory, sent_messages):
    tracker = tracker_factory()
    with app.app_context(), pytest.raises(ValueError, match="Add at least one recipient before sending."):
        sending.send_report(db, tracker, WEEK, "manual", None, NOW)
    assert sent_messages == [] and db.query(ReportSend).count() == 0


def test_test_send_goes_only_to_current_user(app, client, db, tracker_with_recipient, user_factory, sent_messages):
    owner = user_factory(is_admin=True)
    sign_in(client, owner)
    response = post(client, f"/trackers/{tracker_with_recipient.id}/mail/test?week=2026-09-11")
    assert response.status_code == 302
    assert len(sent_messages) == 1 and sent_messages[0]["Bcc"] == owner.email
    assert "a@example.com" not in str(sent_messages[0]["Bcc"])
    assert db.query(ReportSend).count() == 0


def test_every_email_takes_the_tools_subject_not_a_saved_tracker_subject(
    app, db, tracker_with_recipient, sent_messages
):
    db.add(EmailTemplate(tracker_id=tracker_with_recipient.id, subject="Old {{status}}", body_html="<p>Body</p>"))
    db.add(AppSetting(key="report_email_subject", value="[PMO] {{summary}}"))
    db.commit()
    with app.app_context():
        sending.send_report(db, tracker_with_recipient, WEEK, "manual", None, NOW)
    (msg,) = sent_messages
    assert msg["Subject"].startswith("[PMO] Test tracker | 11/09/26 : No status | ")
    assert "<p>Body</p>" in msg.get_body(("html",)).get_content()


def test_without_a_saved_subject_the_summary_is_used(db):
    assert report_subject(db) == "{{summary}}"
    db.add(AppSetting(key="report_email_subject", value="Weekly: {{summary}}"))
    db.commit()
    assert report_subject(db) == "Weekly: {{summary}}"


# --- Database: routes ----------------------------------------------------------------------------------------


def test_mail_settings_owner_only(client, db, tracker_factory, user_factory, grant):
    tracker = tracker_factory()
    editor, viewer = user_factory(), user_factory()
    grant(editor, tracker, "editor")
    grant(viewer, tracker, "viewer")
    for user in (editor, viewer):
        sign_in(client, user)
        assert client.get(f"/trackers/{tracker.id}/mail").status_code == 404
        assert client.get(f"/trackers/{tracker.id}/mail/preview").status_code == 404
        assert (
            post(client, f"/trackers/{tracker.id}/mail", {"action": "add_recipient", "email": "a@b.com"}).status_code
            == 404
        )
        assert post(client, f"/trackers/{tracker.id}/mail/send").status_code == 404
        assert post(client, f"/trackers/{tracker.id}/mail/test").status_code == 404
    assert db.query(Recipient).count() == 0


def test_owner_manages_recipients(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    url = f"/trackers/{tracker.id}/mail"
    assert post(client, url, {"action": "add_recipient", "email": "  Ann@Example.com "}).status_code == 302
    assert db.query(Recipient).one().email == "ann@example.com"
    assert "already a recipient" in post(
        client, url, {"action": "add_recipient", "email": "ANN@example.com"}, follow_redirects=True
    ).get_data(as_text=True)
    assert "valid email" in post(
        client, url, {"action": "add_recipient", "email": "nope"}, follow_redirects=True
    ).get_data(as_text=True)
    assert db.query(Recipient).count() == 1
    recipient = db.query(Recipient).one()
    post(client, url, {"action": "remove_recipient", "recipient_id": recipient.id})
    assert db.query(Recipient).count() == 0
    assert db.query(AuditLog).filter_by(action="recipient_added").count() == 1


def test_owner_saves_template_and_preview_flags_unknown(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    url = f"/trackers/{tracker.id}/mail"
    post(client, url, {"action": "save_template", "body_html": "<p>{{nope}} {{tracker_name}}</p>"})
    template = db.get(EmailTemplate, tracker.id)
    assert template.body_html == "<p>{{nope}} {{tracker_name}}</p>" and template.subject == "{{summary}}"
    page = client.get(url).get_data(as_text=True)
    assert "nope" in page and "Unknown placeholders" in page
    preview = client.get(f"{url}/preview?week=2026-09-11").get_data(as_text=True)
    assert "Subject: Test tracker | 11/09/26" in preview and "srcdoc" in preview


def test_email_page_shows_the_subject_as_text(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    db.add(AppSetting(key="report_email_subject", value="[PMO] {{summary}}"))
    db.commit()
    page = client.get(f"/trackers/{tracker.id}/mail?week=2026-09-11").get_data(as_text=True)
    hidden = re.search(r'<input type="hidden" id="subject"[^>]*>', page).group(0)
    assert "name=" not in hidden and 'value="[PMO] {{summary}}"' in hidden
    shown = re.search(r'<p class="subject-line"[^>]*>(.*?)</p>', page, re.S).group(1)
    assert html.unescape(shown).startswith("[PMO] Test tracker | 11/09/26 : No status | ")
    assert "Set by an administrator for every tracker." in page and "Change in Email settings" not in page
    assert "The message sent with the report." in page and "The subject and message" not in page


def test_email_settings_holders_get_a_link_to_change_the_subject(client, tracker_factory, user_factory):
    tracker = tracker_factory()
    sign_in(client, user_factory(is_admin=True))
    page = client.get(f"/trackers/{tracker.id}/mail").get_data(as_text=True)
    assert 'href="/admin/smtp"' in page and "Change in Email settings" in page


def test_saving_the_template_never_changes_a_saved_subject(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    db.add(EmailTemplate(tracker_id=tracker.id, subject="Old {{status}}", body_html="<p>old</p>"))
    db.commit()
    response = post(
        client, f"/trackers/{tracker.id}/mail", {"action": "save_template", "subject": "New", "body_html": "<p>new</p>"}
    )
    assert response.status_code == 302
    db.expire_all()
    template = db.get(EmailTemplate, tracker.id)
    assert (template.subject, template.body_html) == ("Old {{status}}", "<p>new</p>")


def test_email_page_shows_the_preview_and_asks_before_sending(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    db.add(Recipient(tracker_id=tracker.id, email="a@example.com", name="Ann"))
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/mail?week=2026-09-11").get_data(as_text=True)
    assert "srcdoc=" in html and "data-shell=" in html and "data-context=" in html
    # The preview frame follows the page's policy: inline styles are dropped and a stylesheet stands in for them.
    assert "email-preview.css" in html and "style=&#34;" not in html
    assert "test-tracker-week-ending-2026-09-11.pdf" in html
    assert "Send to 1 recipient…" in html and "data-inline-confirm" in html
    assert "<strong>Ann</strong> <span>a@example.com</span>" in html
    assert "Automatic sending is off" in html


def test_archived_tracker_refuses_mail_posts(client, db, tracker_factory, user_factory, grant, sent_messages):
    tracker, owner = tracker_factory(status="archived"), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    url = f"/trackers/{tracker.id}/mail"
    for path, data in (
        (url, {"action": "add_recipient", "email": "a@b.com"}),
        (f"{url}/send", {}),
        (f"{url}/test", {}),
    ):
        assert post(client, path, data).status_code == 302
    assert db.query(Recipient).count() == 0 and sent_messages == []


# --- Fix round 1 ---------------------------------------------------------------------------------------------


def render_settings(app, recipients):
    from flask import g, render_template

    tracker = SimpleNamespace(
        id=1, name="T", status="active", group_label="Site", unit_label="d", schedule_enabled=False, send_timezone="UTC"
    )
    user = SimpleNamespace(email="o@example.com", full_name="O", is_admin=True)
    with app.test_request_context("/"):
        g.role = "owner"
        return render_template(
            "mail/settings.html",
            tracker=tracker,
            recipients=recipients,
            values={"subject": "s", "body_html": "<p>x</p>"},
            placeholders=PLACEHOLDERS,
            unknown=[],
            custom=False,
            weeks=[date(2026, 9, 4)],
            week=date(2026, 9, 4),
            preview=None,
            recent=[],
            next_send=None,
            current_user=user,
            blocks=(),
            lead_missing=False,
        )


def test_settings_page_shows_empty_recipient_state(app):
    page = render_settings(app, [])
    assert "No recipients yet." in page
    assert "<th>Email</th>" not in page


def test_settings_page_lists_recipients(app):
    page = render_settings(app, [SimpleNamespace(id=1, email="a@example.com", name="")])
    assert "a@example.com" in page and "No recipients yet." not in page


def queue_send(db, tracker, week=WEEK, **overrides) -> ReportSend:
    values = {
        "tracker_id": tracker.id, "week_ending": week, "trigger": "manual", "status": "queued",
        "recipients": ["a@example.com"], "pdf": b"%PDF-fake", "attempts": 1, "next_attempt_at": NOW,
    }  # fmt: skip
    values.update(overrides)
    send = ReportSend(**values)
    db.add(send)
    db.commit()
    return send


def test_retry_queued_skips_rows_already_sent_by_another_worker(
    app, db, tracker_with_recipient, sent_messages, monkeypatch
):
    """A row another worker finished after this one began must be re-read, not sent again."""
    first = queue_send(db, tracker_with_recipient, WEEK)
    second = queue_send(db, tracker_with_recipient, date(2026, 9, 18), next_attempt_at=NOW + timedelta(seconds=1))
    original = sending._retry_one

    def other_worker_wins(session, send, now):
        if send.id == first.id:
            session.execute(ReportSend.__table__.update().where(ReportSend.id == second.id).values(status="sent"))
        original(session, send, now)

    monkeypatch.setattr(sending, "_retry_one", other_worker_wins)
    with app.app_context():
        assert sending.retry_queued(db, NOW + timedelta(minutes=1)) == 1
    assert len(sent_messages) == 1


def test_retry_queued_poison_row_does_not_block_next(app, db, tracker_with_recipient, monkeypatch):
    poison = queue_send(db, tracker_with_recipient, WEEK)
    good = queue_send(db, tracker_with_recipient, date(2026, 9, 18), next_attempt_at=NOW + timedelta(seconds=1))
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    real = sending.build_report_email

    def explode_once(report, template, recipients, link, pdf, sender=""):
        if report.week_ending == WEEK:
            raise RuntimeError("template exploded")
        return real(report, template, recipients, link, pdf, sender)

    monkeypatch.setattr(sending, "build_report_email", explode_once)
    with app.app_context():
        assert sending.retry_queued(db, NOW + timedelta(minutes=1)) == 2
    db.refresh(poison)
    db.refresh(good)
    assert (poison.status, poison.attempts) == ("queued", 2)
    assert poison.next_attempt_at == NOW + timedelta(minutes=1) + timedelta(minutes=15)
    assert poison.error.startswith("RuntimeError: template exploded")
    assert good.status == "sent" and len(sent) == 1
    assert db.query(AuditLog).filter_by(action="report_send_queued", entity_id=str(poison.id)).count() == 1


def test_owner_manual_send_end_to_end(client, db, tracker_with_recipient, user_factory, grant, sent_messages):
    owner = user_factory()
    grant(owner, tracker_with_recipient, "owner")
    sign_in(client, owner)
    response = post(client, f"/trackers/{tracker_with_recipient.id}/mail/send?week=2026-09-11")
    assert response.status_code == 302
    send = db.query(ReportSend).one()
    assert send.status == "sent" and send.trigger == "manual" and send.created_by == owner.id
    assert send.recipients == ["a@example.com"] and send.pdf == b"%PDF-fake"
    assert len(sent_messages) == 1 and sent_messages[0]["Bcc"] == "a@example.com"
    assert db.query(AuditLog).filter_by(action="report_sent").count() == 1
    assert "was sent" in client.get(response.headers["Location"]).get_data(as_text=True)


# --- Pure: the message blocks ---------------------------------------------------------------------------------


def risk(ref, rag="Amber", description="d", owner="Lead", due=None):
    return SimpleNamespace(ref=ref, rag=rag, description=description, owner_role=owner, target_date=due)


def body_report(inputs=("Green", "", ""), unit="devices", **changes):
    report, _ = synthetic_report()
    report.tracker.unit_label = unit
    report.inputs = SimpleNamespace(status=inputs[0], headline=inputs[1], decisions=inputs[2]) if inputs else None
    values = {
        "next_week_target": 4,
        "required_rate": 4.8,
        "target_completion": date(2027, 6, 18),
        "forecast_completion": date(2027, 6, 11),
    }
    report.headline = dataclasses.replace(report.headline, **(values | changes))
    report.top_risks, report.new_risks, report.open_risks = [], [], 0
    return report


def test_figures_are_in_the_agreed_order_with_their_colours():
    from tracker.mail.blocks import figure_items

    assert figure_items(body_report()) == [
        ("Next week's target", "4 devices", "red"),
        ("Needed per week", "4.8 devices", "plain"),
        ("Target finish", "18 Jun 2027", "plain"),
        ("Forecast finish", "11 Jun 2027", "green"),
        ("Status", "Green", "green"),
    ]


@pytest.mark.parametrize(
    "changes, inputs, expected",
    [
        ({"next_week_target": 5}, ("Amber", "", ""), {0: ("5 devices", "green"), 4: ("Amber", "amber")}),
        ({"forecast_completion": date(2027, 6, 25)}, ("Red", "", ""), {3: ("25 Jun 2027", "red"), 4: ("Red", "red")}),
        ({"forecast_completion": date(2027, 6, 18)}, None, {3: ("18 Jun 2027", "green"), 4: ("No status", "none")}),
        (
            {"next_week_target": None, "required_rate": None, "target_completion": None, "forecast_completion": None},
            ("Green", "", ""),
            {0: ("Not set", "plain"), 1: ("Not set", "plain"), 2: ("Not set", "plain"), 3: ("Not set", "plain")},
        ),
    ],
)
def test_figure_colours_and_missing_values(changes, inputs, expected):
    from tracker.mail.blocks import figure_items

    items = figure_items(body_report(inputs=inputs, **changes))
    for index, (value, tone) in expected.items():
        assert items[index][1:] == (value, tone)


def test_figures_without_a_unit_show_plain_numbers():
    from tracker.mail.blocks import figure_items

    items = figure_items(body_report(unit=""))
    assert items[0][1] == "4" and items[1][1] == "4.8"


def test_this_week_and_needed_from_you_are_bullets_one_per_line():
    context = placeholder_context(body_report(inputs=("Green", "Floor 3 done\n\n- Two held back", "Approve <b>")), LINK)
    assert "<li>Floor 3 done</li><li>Two held back</li>" in context["this_week"]
    assert (
        "Needed from you" in context["needed_from_you"] and "<li>Approve &lt;b&gt;</li>" in context["needed_from_you"]
    )


def test_without_an_update_the_message_says_so_and_needed_from_you_is_left_out():
    context = placeholder_context(body_report(inputs=("Green", "  ", "")), LINK)
    assert "No update was written for this week." in context["this_week"]
    assert context["needed_from_you"] == ""
    assert "No update was written for this week." in placeholder_context(body_report(inputs=None), LINK)["this_week"]


def test_risks_table_marks_new_risks_and_adds_those_outside_the_top_three():
    report = body_report()
    top = [risk("R-01", "Red"), risk("R-02"), risk("R-03", "Green")]
    raised = risk("R-09", None, description="Late <stock>", due=date(2026, 11, 20))
    report.top_risks, report.new_risks, report.open_risks = top, [top[0], raised], 5
    html_out = placeholder_context(report, LINK)["risks"]
    assert "Risks: 5" in html_out
    refs = re.findall(r">(R-\d\d)<", html_out)
    assert refs == ["R-01", "R-02", "R-03", "R-09"]
    assert html_out.count(">NEW<") == 2 and "Late &lt;stock&gt;" in html_out and "20/11/26" in html_out


def test_no_open_risks_leaves_the_risks_part_out():
    assert placeholder_context(body_report(), LINK)["risks"] == ""


def test_the_default_message_is_the_four_parts_and_the_subject_ignores_them():
    assert DEFAULT_BODY.split() == ["{{figures}}", "{{this_week}}", "{{needed_from_you}}", "{{risks}}"]
    context = placeholder_context(body_report(inputs=("Green", "x", "")), LINK)
    assert render_subject("A {{figures}}{{this_week}} B", context) == "A  B"
    assert render_placeholders("{{this_week}}", context).startswith('<h3 class="mail-heading"')


def test_email_chart_is_a_png_with_and_without_data():
    from report_helpers import WEEKS, sample_rows

    from tracker.report.charts import email_chart

    assert email_chart(sample_rows(), "devices", WEEKS[1]).startswith(b"\x89PNG")
    assert email_chart([], "", WEEKS[1]).startswith(b"\x89PNG")


def test_the_email_has_one_report_link_and_a_readable_text_part(app):
    report = body_report(inputs=("Green", "Floor 3 done", "Approve"))
    report.top_risks, report.open_risks = [risk("R-01", "Red", description="Firmware")], 1
    msg = email_for(app, report=report)
    page = msg.get_body(preferencelist=("html",)).get_content()
    assert page.count(LINK) == 1 and "No update" not in page
    text_part = msg.get_body(preferencelist=("plain",)).get_content()
    assert "- Floor 3 done" in text_part and "R-01" in text_part and "Firmware" in text_part
