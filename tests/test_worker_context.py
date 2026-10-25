"""The scheduler worker renders inside ``app.app_context()`` only (no request); nothing may need a request."""

from __future__ import annotations

from report_helpers import synthetic_report

from tracker.auth.session import current_user
from tracker.mail.compose import build_report_email
from tracker.report.render import render_print_html


def test_current_user_is_none_without_request_context(app):
    with app.app_context():
        assert current_user() is None


def test_render_print_html_in_app_context_only(app):
    report, _ = synthetic_report()
    with app.app_context():
        html = render_print_html(report)
    assert "Stub tracker" in html


def test_build_report_email_in_app_context_only(app):
    report, _ = synthetic_report()
    with app.app_context():
        msg = build_report_email(report, None, ["a@example.com"], "https://tracker.example/r", b"%PDF-1.4")
    assert "Stub tracker" in msg["Subject"]
    assert "https://tracker.example/r" in msg.get_body(("html",)).get_content()
