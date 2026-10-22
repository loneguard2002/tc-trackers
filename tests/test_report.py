"""Report model, charts and the live report page. Engine-level and chart tests need no database."""

from __future__ import annotations

import base64
import re
from datetime import date
from types import SimpleNamespace

import pytest

from tracker.engine.calc import WeekRow, build_week_rows
from tracker.formatting import fmt_dash, fmt_date, fmt_pct, fmt_rate
from tracker.models import CompletionEntry, Group, ReportInput, Risk, Week
from tracker.report.build import build_report, default_report_week, select_top_risks
from tracker.report.charts import cumulative_chart, remaining_chart, weekly_chart

FRIDAY = 4
STUB_USER = SimpleNamespace(is_admin=False, full_name="Test User")
BADGE_IN_PROGRESS = '<span class="badge badge-info">In progress</span>'
WEEKS = [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25)]


def sample_rows() -> list[WeekRow]:
    return build_week_rows(
        WEEKS,
        {w: 10 for w in WEEKS},
        {WEEKS[0]: 8, WEEKS[1]: 12},
        100,
        0,
        3,
        date(2026, 9, 12),
        FRIDAY,
    )


# --- Charts and formatting (no database) ----------------------------------------------------------------------


def test_charts_return_svg_and_png():
    rows = sample_rows()
    for make in (
        lambda f: remaining_chart(rows, "devices", f),
        lambda f: weekly_chart(rows, f),
        lambda f: cumulative_chart(rows, f),
    ):
        assert b"<svg" in make("svg")
        assert make("png").startswith(b"\x89PNG")


def test_charts_render_with_no_rows_and_with_all_none():
    empty = [WeekRow(w, None, None, None, None, None, None, None, None, None, None, "future") for w in WEEKS]
    for rows in ([], empty):
        for data in (remaining_chart(rows, "devices", "svg"), weekly_chart(rows, "svg"), cumulative_chart(rows, "svg")):
            assert b"<svg" in data
        assert remaining_chart(rows, "devices", "png").startswith(b"\x89PNG")


def test_chart_rejects_unknown_format():
    with pytest.raises(ValueError):
        weekly_chart(sample_rows(), "gif")


def test_formatting_filters():
    assert fmt_pct(0.374) == "37%" and fmt_pct(None) == "–"
    assert fmt_rate(33.333) == "33.3" and fmt_rate(None) == "–"
    assert fmt_date(date(2026, 10, 16)) == "16 Oct 2026" and fmt_date(date(2026, 10, 6)) == "06 Oct 2026"
    assert fmt_date(None) == "–" and fmt_dash("") == "–" and fmt_dash(0) == "0"


def test_filters_registered_in_app(app):
    assert {"pct", "rate", "fdate", "dash", "data_uri"} <= set(app.jinja_env.filters)


def test_csp_allows_data_images(client):
    assert "img-src 'self' data:" in client.get("/healthz").headers["Content-Security-Policy"]


def test_top_risks_order():
    def risk(ref, rag, target, status="Open"):
        return SimpleNamespace(ref=ref, rag=rag, target_date=target, status=status)

    risks = [
        risk("R1", "Amber", date(2026, 9, 1)),
        risk("R2", "Red", date(2026, 12, 1)),
        risk("R3", "Green", date(2026, 9, 1)),
        risk("R4", None, date(2026, 9, 1)),
        risk("R5", "Red", None),
        risk("R6", "Red", date(2026, 10, 1), status="Closed"),
        risk("R7", "Red", date(2026, 12, 1)),
    ]
    assert [r.ref for r in select_top_risks(risks)] == ["R2", "R7", "R5"]
    assert [r.ref for r in select_top_risks(risks[:5] + [risks[6]], limit=10)][:5] == ["R2", "R7", "R5", "R1", "R3"]


def test_default_report_week_pure():
    tracker = SimpleNamespace(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    assert default_report_week(tracker, date(2026, 9, 12)) == WEEKS[0] + (WEEKS[1] - WEEKS[0])
    assert default_report_week(tracker, date(2026, 9, 1)) == WEEKS[0]
    assert default_report_week(tracker, date(2027, 1, 1)) == WEEKS[-1]


# --- Database-backed -----------------------------------------------------------------------------------------


def seed(db, tracker, baseline=100):
    group = Group(tracker_id=tracker.id, name="Site A", baseline=baseline, sort_order=1)
    db.add(group)
    db.flush()
    for week in WEEKS:
        db.add(Week(tracker_id=tracker.id, week_ending=week, target=10))
    db.add(
        CompletionEntry(
            tracker_id=tracker.id, group_id=group.id, quantity=8, entry_date=date(2026, 9, 3), week_ending=WEEKS[0]
        )
    )
    db.add(
        CompletionEntry(
            tracker_id=tracker.id, group_id=group.id, quantity=12, entry_date=date(2026, 9, 10), week_ending=WEEKS[1]
        )
    )
    db.commit()
    return group


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1], target_completion=date(2026, 12, 25))


def test_build_report_defaults_to_last_completed_week(db, small_tracker):
    seed(db, small_tracker)
    report = build_report(db, small_tracker, None, date(2026, 9, 14))
    assert report.week_ending == WEEKS[1] and report.as_of == WEEKS[1]
    assert report.in_progress is False
    assert report.headline.completed == 20


def test_build_report_marks_in_progress(db, small_tracker):
    seed(db, small_tracker)
    report = build_report(db, small_tracker, WEEKS[2], date(2026, 9, 14))
    assert report.in_progress is True and report.as_of == date(2026, 9, 14)
    assert set(report.charts) == {"remaining", "weekly", "cumulative"}


def test_build_report_risk_counts_and_inputs(db, small_tracker):
    seed(db, small_tracker)
    for ref, rag, status in (("R1", "Red", "Open"), ("R2", "Amber", "In progress"), ("R3", "Red", "Closed")):
        db.add(Risk(tracker_id=small_tracker.id, ref=ref, rag=rag, status=status))
    db.add(
        ReportInput(
            tracker_id=small_tracker.id, week_ending=WEEKS[1], status="Amber", headline="Slow week", decisions=""
        )
    )
    db.commit()
    report = build_report(db, small_tracker, WEEKS[1], date(2026, 9, 14))
    assert (report.open_risks, report.red_risks) == (2, 1)
    assert [r.ref for r in report.top_risks] == ["R1", "R2"]
    assert report.inputs.status == "Amber"


@pytest.fixture
def viewer(client, logged_in_user, grant, small_tracker):
    grant(logged_in_user, small_tracker, "viewer")
    return logged_in_user


def test_report_page_renders_sections(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    db.add(
        ReportInput(
            tracker_id=small_tracker.id,
            week_ending=WEEKS[1],
            status="Amber",
            headline="Slow week",
            decisions="Approve extra staff",
        )
    )
    db.commit()
    page = client.get(f"/trackers/{small_tracker.id}/report?week={WEEKS[1].isoformat()}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Needed from you" in html and "Approve extra staff" in html and "Amber" in html
    assert "Site A" in html and "Rate (3 wk)" in html
    assert html.count("data:image/svg+xml;base64,") == 3
    assert BADGE_IN_PROGRESS not in html


def test_report_page_in_progress_badge_and_bad_week(client, db, small_tracker, viewer, monkeypatch):
    seed(db, small_tracker)
    base = f"/trackers/{small_tracker.id}/report"
    assert client.get(f"{base}?week=2099-01-01").status_code == 404
    assert client.get(f"{base}?week=nonsense").status_code == 400
    monkeypatch.setattr("tracker.report.views.today", lambda: date(2026, 9, 21))
    future = client.get(f"{base}?week={WEEKS[-1].isoformat()}")
    assert future.status_code == 200 and BADGE_IN_PROGRESS in future.get_data(as_text=True)
    past = client.get(f"{base}?week={WEEKS[0].isoformat()}")
    assert BADGE_IN_PROGRESS not in past.get_data(as_text=True)


def test_report_page_empty_tracker(client, small_tracker, viewer):
    page = client.get(f"/trackers/{small_tracker.id}/report")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "No forecast yet" in html and "Not set" in html and "No open risks" in html


def test_report_figures_match_engine(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    report = build_report(db, small_tracker, WEEKS[1], date.today())
    html = client.get(f"/trackers/{small_tracker.id}/report?week={WEEKS[1].isoformat()}").get_data(as_text=True)
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert f"{report.headline.completed} of {report.headline.total_scope}" in flat
    assert fmt_date(report.headline.forecast_completion) in flat
    assert report.headline.verdict in flat


def test_report_requires_a_role(client, logged_in_user, small_tracker):
    assert client.get(f"/trackers/{small_tracker.id}/report").status_code == 404


def test_charts_embed_decodes_to_svg(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    html = client.get(f"/trackers/{small_tracker.id}/report").get_data(as_text=True)
    payload = re.search(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", html).group(1)
    assert b"<svg" in base64.b64decode(payload)


def test_home_shows_weekly_status_from_latest_input(client, db, small_tracker, viewer):
    assert "Not set" in client.get("/").get_data(as_text=True)
    db.add(ReportInput(tracker_id=small_tracker.id, week_ending=WEEKS[0], status="Red"))
    db.add(ReportInput(tracker_id=small_tracker.id, week_ending=WEEKS[1], status="Green"))
    db.commit()
    html = client.get("/").get_data(as_text=True)
    assert 'badge-success">Green</span>' in html
    assert 'badge-danger">Red</span>' not in html


# --- Template rendering without a database ----------------------------------------------------------------------


def synthetic_report(in_progress: bool = False):
    from tracker.engine.calc import GroupInput, build_headline, group_positions
    from tracker.report.build import Report

    rows = sample_rows()
    positions = group_positions([GroupInput(1, "Site A", 100, 0, 0, None, "Red", "c", False)], {1: 20})
    headline = build_headline(rows, positions, 0, date(2026, 12, 25), WEEKS[1])
    tracker = SimpleNamespace(
        id=1, name="Stub tracker", unit_label="devices", group_label="Site", moving_average_weeks=3, status="active"
    )
    risk = SimpleNamespace(ref="R1", description="d", status="In progress", rag="Red", target_date=None)
    charts = {
        "remaining": remaining_chart(rows, "devices"),
        "weekly": weekly_chart(rows),
        "cumulative": cumulative_chart(rows),
    }
    report = Report(tracker, WEEKS[1], WEEKS[1], in_progress, rows, headline, positions, [risk], 1, 1, None, charts)
    return report, tracker


def test_report_page_template_renders_without_database(app):
    from flask import g, render_template

    report, tracker = synthetic_report()
    with app.test_request_context("/"):
        g.role, g.tracker = "viewer", tracker
        g.current_user = STUB_USER  # read by the app's context processor, with or without a database
        html = render_template(
            "report/page.html",
            tracker=tracker,
            report=report,
            weeks=WEEKS,
            page_title="x",
            current_page="trackers",
        )
    assert "Stub tracker" in html and "Needed from you" in html and html.count("data:image/svg+xml;base64,") == 3
    assert BADGE_IN_PROGRESS not in html


def test_report_body_in_progress_badge_without_database(app):
    from flask import render_template

    report, _ = synthetic_report(in_progress=True)
    with app.test_request_context("/"):
        html = render_template("report/_body.html", report=report)
    assert BADGE_IN_PROGRESS in html


def render_page(app, report, tracker, user):
    from flask import g, render_template

    with app.test_request_context("/"):
        g.role, g.tracker, g.current_user = "viewer", tracker, user
        return render_template(
            "report/page.html", tracker=tracker, report=report, weeks=WEEKS, page_title="x", current_page="trackers"
        )


def test_report_page_tolerates_anonymous_user(app):
    report, tracker = synthetic_report()
    assert "Stub tracker" in render_page(app, report, tracker, None)


def test_empty_report_renders_expected_messages_without_database(app):
    from tracker.engine.calc import build_headline, build_week_rows
    from tracker.report.build import Report

    rows = build_week_rows(WEEKS, {}, {}, 0, 0, 3, date(2026, 10, 22), FRIDAY)
    headline = build_headline(rows, [], 0, date(2026, 12, 25), WEEKS[-1])
    tracker = SimpleNamespace(
        id=1, name="Empty", unit_label="devices", group_label="", moving_average_weeks=3, status="active"
    )
    charts = {
        "remaining": remaining_chart(rows, "d"),
        "weekly": weekly_chart(rows),
        "cumulative": cumulative_chart(rows),
    }
    report = Report(tracker, WEEKS[-1], WEEKS[-1], False, rows, headline, [], [], 0, 0, None, charts)
    html = render_page(app, report, tracker, STUB_USER)
    assert headline.verdict == "No forecast yet"
    assert "No forecast yet" in html and "Not set" in html and "No open risks" in html
