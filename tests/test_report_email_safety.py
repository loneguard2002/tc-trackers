"""Audit 2026-11-25, Medium 1: a tracker owner's email body is cleaned to formatting, lists, tables and safe links, and
report emails go only to addresses at the domains an administrator allows (tracker/mail/compose.py, domains.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from conftest import post, sign_in
from report_helpers import synthetic_report

from tracker.mail import domains, sending, smtp
from tracker.mail.compose import build_report_email, clean_body, removed_parts
from tracker.models import AppSetting, AuditLog, EmailTemplate, Recipient, ReportSend

NOW = datetime(2026, 9, 11, 17, 0, tzinfo=timezone.utc)
WEEK = date(2026, 9, 11)
LINK = "https://tracker.example.com/trackers/1/report?week=2026-09-11"


# --- Cleaning the body (no database) --------------------------------------------------------------------------------


def test_formatting_lists_tables_links_and_placeholders_are_kept():
    body = (
        "<h3>This week</h3><p>Hello <strong>all</strong>, <em>see</em> <u>below</u>.<br>{{tracker_name}}</p>"
        "<ul><li>One</li></ul><ol><li>Two</li></ol>{{figures}}"
        '<p><a href="https://intranet.example.com/a?b=1">guide</a> <a href="mailto:pmo@tradition.ch">mail</a> '
        '<a href="{{report_link}}">report</a></p>'
    )
    assert clean_body(body) == body
    assert removed_parts(body) == []
    table = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    assert "<td>1</td>" in clean_body(table) and removed_parts(table) == []


@pytest.mark.parametrize(
    "unsafe",
    [
        '<a href="http://login.example.net">x</a>',
        '<a href="javascript:alert(1)">x</a>',
        '<a href="//login.example.net">x</a>',
        '<a href="data:text/html,hi">x</a>',
        '<a href=" {{tracker_name}} ">x</a>',
    ],
)
def test_a_link_that_is_not_https_mailto_or_the_report_link_loses_its_address(unsafe):
    assert clean_body(unsafe) == "<a>x</a>"
    assert removed_parts(unsafe) == ["a link that is not https or mailto"]


def test_scripts_handlers_styles_images_forms_and_comments_are_removed():
    body = (
        '<p onclick="steal()" style="color:red" class="x">Text</p><script>alert(1)</script><style>p{}</style>'
        '<img src="https://e.example/t.png"><form action="https://e.example"><input name="p">Login</form><!-- note -->'
        '<iframe src="https://e.example">frame</iframe>'
    )
    assert clean_body(body) == "<p>Text</p>Login"
    assert removed_parts(body) == [
        "the onclick attribute",
        "style attributes",
        "class attributes",
        "<script>",
        "<style>",
        "<img>",
        "<form>",
        "<input>",
        "comments",
        "<iframe>",
    ]


def test_the_email_built_from_a_template_saved_before_cleaning_is_cleaned(app):
    template = type(
        "T", (), {"subject": "{{tracker_name}}", "body_html": '<p onclick="x">Hi</p><script>bad()</script>'}
    )
    with app.test_request_context("/"):
        msg = build_report_email(synthetic_report()[0], template, ["a@example.com"], LINK, b"%PDF")
    page = msg.get_body(preferencelist=("html",)).get_content()
    assert "<p>Hi</p>" in page and "onclick" not in page and "bad()" not in page


# --- The allowed domains (no database) -------------------------------------------------------------------------------


def test_the_domain_list_is_parsed_one_per_line_without_the_at():
    assert domains.parse_domains("Tradition.com\n@tradition.ch, traditiondata.com\n\ntradition.com") == (
        ["tradition.com", "tradition.ch", "traditiondata.com"],
        None,
    )
    assert domains.parse_domains("  \n ") == ([], domains.EMPTY_ERROR)
    assert domains.parse_domains("not a domain") == ([], domains.DOMAIN_ERROR)
    assert domains.parse_domains("a@b.com") == ([], domains.DOMAIN_ERROR)
    assert domains.parse_domains("\n".join(f"d{i}.com" for i in range(51))) == ([], domains.TOO_MANY_ERROR)


def test_an_address_matches_only_its_exact_domain():
    allowed = ["tradition.com", "tradition.ch"]
    assert domains.is_allowed("Ann@Tradition.COM", allowed)
    assert not domains.is_allowed("ann@uk.tradition.com", allowed)  # a sub-domain needs its own line
    assert not domains.is_allowed("ann@tradition.com.example.net", allowed)
    assert domains.split_recipients(["a@tradition.ch", "b@example.org"], allowed) == (
        ["a@tradition.ch"],
        ["b@example.org"],
    )


# --- With a database ------------------------------------------------------------------------------------------------


def test_until_a_list_is_saved_the_organisations_four_domains_are_allowed(db, real_recipient_domains):
    assert domains.allowed_domains(db) == ["tradition.com", "tradition.ch", "traditiondata.com", "traditionasia.com"]
    db.add(AppSetting(key=domains.KEY, value="tradition.ch\nexample.org"))
    db.commit()
    assert domains.allowed_domains(db) == ["tradition.ch", "example.org"]


@pytest.fixture
def owner_client(client, db, tracker_factory, user_factory, grant):
    tracker, owner = tracker_factory(), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    return tracker


def test_an_owner_cannot_add_a_recipient_outside_the_allowed_domains(client, db, owner_client, real_recipient_domains):
    url = f"/trackers/{owner_client.id}/mail"
    page = post(client, url, {"action": "add_recipient", "email": "buyer@client.example"}, follow_redirects=True)
    text = page.get_data(as_text=True)
    assert "client.example is not an allowed domain" in text and "tradition.com, tradition.ch" in text
    assert db.query(Recipient).count() == 0
    assert post(client, url, {"action": "add_recipient", "email": "pmo@Tradition.ch"}).status_code == 302
    assert [r.email for r in db.query(Recipient)] == ["pmo@tradition.ch"]


def test_the_email_tab_marks_a_recipient_that_is_not_sent_to(client, db, owner_client, real_recipient_domains):
    db.add_all(
        [
            Recipient(tracker_id=owner_client.id, email="pmo@tradition.ch"),
            Recipient(tracker_id=owner_client.id, email="old@client.example"),
        ]
    )
    db.commit()
    page = client.get(f"/trackers/{owner_client.id}/mail").get_data(as_text=True)
    assert page.count("Not sent: domain not allowed") == 1 and "1 is not sent to" in page
    assert "Send to 1 recipient…" in page  # only the one who will get it
    assert "Only addresses at tradition.com, tradition.ch, traditiondata.com or traditionasia.com can be added" in page


def test_a_send_skips_recipients_outside_the_list_and_records_them(
    app, db, tracker_factory, real_recipient_domains, monkeypatch
):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    monkeypatch.setattr(sending, "html_to_pdf", lambda html: b"%PDF-fake")
    tracker = tracker_factory()
    db.add_all(
        [
            Recipient(tracker_id=tracker.id, email="pmo@tradition.ch"),
            Recipient(tracker_id=tracker.id, email="x@client.example"),
        ]
    )
    db.commit()
    with app.app_context():
        send = sending.send_report(db, tracker, WEEK, "manual", None, NOW)
    assert send.status == "sent" and send.recipients == ["pmo@tradition.ch"]
    assert sent[0]["Bcc"] == "pmo@tradition.ch"
    audit = db.query(AuditLog).filter_by(action="report_sent").one()
    assert audit.detail["skipped_recipients"] == ["x@client.example"]


def test_a_send_with_no_allowed_recipient_is_refused(app, db, tracker_factory, real_recipient_domains, monkeypatch):
    monkeypatch.setattr(smtp, "send_message", lambda msg: pytest.fail("nothing should be sent"))
    tracker = tracker_factory()
    db.add(Recipient(tracker_id=tracker.id, email="x@client.example"))
    db.commit()
    with app.app_context(), pytest.raises(ValueError, match="None of the recipients"):
        sending.send_report(db, tracker, WEEK, "manual", None, NOW)


def test_a_retry_skips_a_domain_taken_off_the_list_since(app, db, tracker_factory, real_recipient_domains, monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    tracker = tracker_factory()
    send = ReportSend(
        tracker_id=tracker.id, week_ending=WEEK, trigger="manual", status="queued",
        recipients=["pmo@tradition.ch", "ops@traditionasia.com"], pdf=b"%PDF", attempts=1, next_attempt_at=NOW,
    )  # fmt: skip
    db.add(send)
    db.add(AppSetting(key=domains.KEY, value="tradition.ch"))
    db.commit()
    with app.app_context():
        sending.retry_queued(db, NOW)
    db.refresh(send)
    assert send.status == "sent" and send.recipients == ["pmo@tradition.ch"] and sent[0]["Bcc"] == "pmo@tradition.ch"
    db.query(AppSetting).filter_by(key=domains.KEY).one().value = "tradition.com"
    send.status, send.next_attempt_at = "queued", NOW
    db.commit()
    with app.app_context():
        sending.retry_queued(db, NOW)
    db.refresh(send)
    assert send.status == "failed" and send.error == sending.NONE_ALLOWED_MESSAGE and len(sent) == 1


def test_saving_the_template_stores_it_cleaned_and_says_what_was_removed(client, db, owner_client):
    url = f"/trackers/{owner_client.id}/mail"
    page = post(
        client,
        url,
        {
            "action": "save_template",
            "body_html": '<p onclick="x">Hi {{tracker_name}}</p><a href="http://e.example">go</a>',
        },
        follow_redirects=True,
    ).get_data(as_text=True)
    assert db.get(EmailTemplate, owner_client.id).body_html == "<p>Hi {{tracker_name}}</p><a>go</a>"
    assert "Removed because an email cannot carry them safely: the onclick attribute, a link that is not https" in page
    entry = db.query(AuditLog).filter_by(action="email_template_saved").one()
    assert entry.detail["removed"] == ["the onclick attribute", "a link that is not https or mailto"]
    refused = post(client, url, {"action": "save_template", "body_html": "<script>only()</script>"})
    assert refused.status_code == 400 and db.get(EmailTemplate, owner_client.id).body_html.startswith("<p>Hi")


# --- Email settings: the list, administrators only ------------------------------------------------------------------


def test_an_administrator_changes_the_list_and_it_is_recorded(client, db, logged_in_admin, real_recipient_domains):
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert (
        'name="recipient_domains"' in page
        and "tradition.com\ntradition.ch\ntraditiondata.com\ntraditionasia.com" in page
    )
    assert (
        post(
            client,
            "/admin/smtp",
            {"smtp_auth": "none", "recipient_domains": "tradition.com\n@Client.Example\ntradition.ch"},
        ).status_code
        == 302
    )
    assert domains.allowed_domains(db) == ["tradition.com", "client.example", "tradition.ch"]
    entry = db.query(AuditLog).filter_by(action="recipient_domains_changed").one()
    assert entry.detail == {"added": ["client.example"], "removed": ["traditiondata.com", "traditionasia.com"]}
    assert (
        post(client, "/admin/smtp", {"smtp_auth": "none", "recipient_domains": " "}).status_code == 400
    )  # never empty
    assert post(client, "/admin/smtp", {"smtp_auth": "none", "recipient_domains": "not a domain"}).status_code == 400
    assert domains.allowed_domains(db) == ["tradition.com", "client.example", "tradition.ch"]


def test_an_email_settings_holder_who_is_not_an_administrator_sees_the_list_read_only(
    client, db, user_factory, give_set, real_recipient_domains
):
    holder = user_factory()
    give_set(["manage_email_settings"], user=holder)
    sign_in(client, holder)
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert 'name="recipient_domains"' not in page and "@traditionasia.com" in page
    assert "Only an administrator can change this list." in page
    assert post(client, "/admin/smtp", {"recipient_domains": "client.example"}).status_code == 400
    assert post(client, "/admin/smtp", {"smtp_from": "pt@tradition.ch"}).status_code == 302  # the rest still saves
    assert db.query(AppSetting).filter_by(key=domains.KEY).count() == 0
