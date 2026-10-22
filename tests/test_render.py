"""PDF and PNG export. Rendering tests need no database; the route tests do."""

from __future__ import annotations

import re
from datetime import date

import pytest
from report_helpers import synthetic_report

from tracker.report.render import html_to_pdf, html_to_png, render_print_html


def print_html(app, **kwargs) -> str:
    report, _ = synthetic_report(**kwargs)
    with app.test_request_context("/"):
        return render_print_html(report)


def test_print_html_self_contained(app):
    html = print_html(app)
    assert "data:image/svg+xml" in html
    assert "<script" not in html
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html)
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")  # only the SVG namespace may appear
    assert "<style>" in html and ".report" in html and "url_for" not in html
    assert "<link" not in html
    assert "Stub tracker" in html


def test_print_html_is_standalone_a4_document(app):
    html = print_html(app)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "@page" in html and "A4" in html


@pytest.fixture
def html(app):
    return print_html(app)


@pytest.mark.browser
def test_pdf_bytes(html):
    assert html_to_pdf(html)[:4] == b"%PDF"


@pytest.mark.browser
def test_png_bytes(html):
    assert html_to_png(html)[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.browser
def test_png_width_is_respected(html):
    import struct

    data = html_to_png(html, width=900)
    assert struct.unpack(">II", data[16:24])[0] == 900


# --- Routes (database) ------------------------------------------------------------------------------------------


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(name="Core Rollout", first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 9, 25))


@pytest.fixture
def viewer(client, logged_in_user, grant, small_tracker):
    grant(logged_in_user, small_tracker, "viewer")
    return logged_in_user


@pytest.mark.parametrize("extension", ["pdf", "png"])
def test_report_export_requires_role(client, logged_in_user, small_tracker, extension):
    assert client.get(f"/trackers/{small_tracker.id}/report.{extension}").status_code == 404


def test_report_export_bad_week(client, small_tracker, viewer):
    assert client.get(f"/trackers/{small_tracker.id}/report.pdf?week=nonsense").status_code == 400
    assert client.get(f"/trackers/{small_tracker.id}/report.pdf?week=2030-01-04").status_code == 404


@pytest.mark.browser
def test_report_pdf_download_headers(client, small_tracker, viewer, monkeypatch):
    monkeypatch.setattr("tracker.report.views.today", lambda: date(2026, 9, 30))
    response = client.get(f"/trackers/{small_tracker.id}/report.pdf?week=2026-09-18")
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    disposition = response.headers["Content-Disposition"]
    assert "attachment" in disposition and "core-rollout-week-ending-2026-09-18.pdf" in disposition
    assert response.data[:4] == b"%PDF"


@pytest.mark.browser
def test_report_png_download_headers(client, small_tracker, viewer, monkeypatch):
    monkeypatch.setattr("tracker.report.views.today", lambda: date(2026, 9, 30))
    response = client.get(f"/trackers/{small_tracker.id}/report.png")
    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert "core-rollout-week-ending-2026-09-25.png" in response.headers["Content-Disposition"]
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"
