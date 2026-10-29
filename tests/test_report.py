"""Report model, charts and the live report page. Engine-level and chart tests need no database."""

from __future__ import annotations

import base64
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from report_helpers import FRIDAY, WEEKS, sample_rows, synthetic_report

from tracker.engine.calc import WeekRow, build_week_rows
from tracker.formatting import fmt_dash, fmt_date, fmt_num, fmt_pct, fmt_plural, fmt_rate
from tracker.models import CompletionEntry, Group, ReportInput, Risk, Week
from tracker.report.build import build_report, current_report_week, default_report_week, select_top_risks
from tracker.report.chart_data import chart_payload
from tracker.report.charts import (
    PALETTE,
    _series,
    actual_series,
    chart_series,
    cumulative_chart,
    remaining_chart,
    weekly_chart,
)
from tracker.report.render import render_print_html

STUB_USER = SimpleNamespace(is_admin=False, full_name="Test User")
BADGE_IN_PROGRESS = '<span class="badge badge-info">In progress</span>'


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


def _points(rows, values):
    return [(r.week_ending, v) for r, v in zip(rows, values) if v is not None]


def test_chart_series_aligns_with_rows():
    rows = sample_rows()
    series = chart_series(rows)
    assert set(series) == {
        "planned_remaining",
        "actual_remaining",
        "forecast_remaining",
        "target",
        "actual",
        "cum_target",
        "cum_actual",
    }
    assert all(len(values) == len(rows) for values in series.values())


def test_chart_series_matches_the_matplotlib_series():
    rows = sample_rows()
    series = chart_series(rows)
    for key in ("planned_remaining", "target", "actual", "cum_target"):
        assert _points(rows, series[key]) == list(zip(*_series(rows, key)))
    for key in ("actual_remaining", "cum_actual"):
        assert _points(rows, series[key]) == list(zip(*actual_series(rows, key)))


def test_chart_series_forecast_starts_at_the_last_complete_week():
    rows = sample_rows()
    forecast = chart_series(rows)["forecast_remaining"]
    last_complete = max(i for i, r in enumerate(rows) if r.moving_average is not None)
    assert all(v is None for v in forecast[:last_complete])
    assert forecast[last_complete] == rows[last_complete].forecast_remaining


def test_chart_payload_shape():
    rows = sample_rows()
    payload = chart_payload(SimpleNamespace(unit_label="devices"), rows)
    assert payload["palette"] == {"plan": "#888888", "actual": "#2c7be5", "forecast": "#d39e00"} == PALETTE
    assert payload["weeks"] == [w.isoformat() for w in WEEKS]
    assert payload["unit_label"] == "devices"
    assert payload["series"] == chart_series(rows)


def test_formatting_filters():
    assert fmt_pct(0.374) == "37%" and fmt_pct(None) == "–"
    assert fmt_rate(33.333) == "33.3" and fmt_rate(None) == "–"
    assert fmt_date(date(2026, 10, 16)) == "16 Oct 2026" and fmt_date(date(2026, 10, 6)) == "06 Oct 2026"
    assert fmt_date(None) == "–" and fmt_dash("") == "–" and fmt_dash(0) == "0"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Location", "Locations"),
        ("Locations", "Locations"),
        ("Country", "Countries"),
        ("Day", "Days"),
        ("Branch", "Branches"),
        ("Box", "Boxes"),
        ("SITE", "SITES"),
        (" Desk ", "Desks"),
        ("", ""),
    ],
)
def test_plural_filter(label, expected):
    assert fmt_plural(label) == expected


def test_filters_registered_in_app(app):
    assert {"pct", "rate", "fdate", "dash", "data_uri", "plural"} <= set(app.jinja_env.filters)


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


def test_current_report_week_is_the_week_in_progress():
    tracker = SimpleNamespace(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    assert current_report_week(tracker, date(2026, 9, 12)) == WEEKS[2]  # Saturday after week 2 ends
    assert current_report_week(tracker, WEEKS[1]) == WEEKS[1]  # the week-ending day itself
    assert current_report_week(tracker, date(2026, 9, 1)) == WEEKS[0]
    assert current_report_week(tracker, date(2027, 1, 1)) == WEEKS[-1]


def test_weekly_chart_draws_the_week_in_progress_paler():
    rows = sample_rows()  # as of 12 Sep: the week ending 18 Sep is in progress
    assert any(r.state == "in_progress" and r.actual is not None for r in rows)
    assert b"opacity: 0.4" in weekly_chart(rows, "svg")
    complete_only = [r for r in rows if r.state != "in_progress"]
    assert b"opacity: 0.4" not in weekly_chart(complete_only, "svg")


def test_chart_payload_marks_the_week_in_progress():
    rows = sample_rows()
    payload = chart_payload(SimpleNamespace(unit_label="devices"), rows)
    assert payload["in_progress"] == [r.state == "in_progress" for r in rows]
    assert payload["in_progress"].count(True) == 1


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


def test_report_page_opens_on_the_week_in_progress(client, db, small_tracker, viewer, monkeypatch):
    seed(db, small_tracker)
    monkeypatch.setattr("tracker.report.views.today", lambda: date(2026, 9, 14))
    html = client.get(f"/trackers/{small_tracker.id}/report").get_data(as_text=True)
    assert f"week ending {fmt_date(WEEKS[2])}" in html and BADGE_IN_PROGRESS in html
    assert f"data.json?week={WEEKS[2].isoformat()}" in html and f"report.pdf?week={WEEKS[2].isoformat()}" in html
    data = client.get(f"/trackers/{small_tracker.id}/report/data.json").get_json()
    assert data["in_progress"] == [False, False, True, False]


def test_report_page_has_the_preview_switch(client, db, small_tracker, viewer):
    html = client.get(f"/trackers/{small_tracker.id}/report").get_data(as_text=True)
    assert "data-report-view hidden" in html and "report-view.js" in html
    for view in ("screen", "pdf", "png"):
        assert f'data-view="{view}"' in html


def test_report_page_points_charts_at_the_selected_week(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    week = WEEKS[1].isoformat()
    html = client.get(f"/trackers/{small_tracker.id}/report?week={week}").get_data(as_text=True)
    assert f'data-chart-data="/trackers/{small_tracker.id}/report/data.json?week={week}"' in html
    assert "vendor/echarts-6.1.0.min.js" in html and "report-charts.js" in html
    for name in ("remaining", "weekly", "cumulative"):
        assert f'data-chart="{name}"' in html


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
    assert "tracker-card tracker-card-green" in html
    assert "tracker-card-red" not in html


# --- Template rendering without a database ----------------------------------------------------------------------


def test_fmt_num_adds_thousands_separators():
    assert fmt_num(1170) == "1,170" and fmt_num(0) == "0" and fmt_num(None) == "–"


def test_report_page_steps_between_weeks(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    html = client.get(f"/trackers/{small_tracker.id}/report?week={WEEKS[1].isoformat()}").get_data(as_text=True)
    base = f"/trackers/{small_tracker.id}/report"
    assert f'href="{base}?week={WEEKS[0].isoformat()}" rel="prev"' in html
    assert f'href="{base}?week={WEEKS[2].isoformat()}" rel="next"' in html
    first = client.get(f"{base}?week={WEEKS[0].isoformat()}").get_data(as_text=True)
    assert 'rel="prev"' not in first and 'aria-disabled="true"' in first


def test_report_shows_status_colour_risk_stripes_and_group_bars(client, db, small_tracker, viewer):
    group = seed(db, small_tracker)
    group.rag, group.planned_completion, group.comment = "Amber", date(2026, 12, 4), "Waiting on stock"
    db.add(ReportInput(tracker_id=small_tracker.id, week_ending=WEEKS[1], status="Red"))
    db.add(
        Risk(
            tracker_id=small_tracker.id,
            ref="R1",
            description="Late stock",
            rag="Red",
            group_id=group.id,
            target_date=date(2026, 9, 1),
        )
    )
    db.commit()
    html = client.get(f"/trackers/{small_tracker.id}/report?week={WEEKS[1].isoformat()}").get_data(as_text=True)
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "report-band report-band-red" in html and "top-risk top-risk-red" in html
    assert "Late stock" in flat and "Site A" in flat and "target 01 Sep 2026, passed" in flat
    assert "planned 04 Dec 2026 · Waiting on stock" in flat
    assert 'class="bar-fill" width="20.00"' in html
    assert "All locations 20 of 100 · 20%" in flat


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
    from tracker.engine.calc import build_headline
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


def test_actual_series_uses_completed_weeks_only():
    from tracker.engine.calc import COMPLETE
    from tracker.report.charts import actual_series

    rows = sample_rows()
    complete = [r.week_ending for r in rows if r.state == COMPLETE]
    assert any(r.state != COMPLETE and r.actual_remaining is not None for r in rows)  # the in-progress row is excluded
    for attr in ("actual_remaining", "cum_actual"):
        xs, _ = actual_series(rows, attr)
        assert xs == complete


# --- Top risks and headline figures (database-free) -------------------------------------------------------------


def body_html(app, report):
    from flask import render_template

    with app.test_request_context("/"):
        return render_template("report/_body.html", report=report)


def flat_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&#39;", "'")


def test_top_risks_show_owner_role(app):
    report, _ = synthetic_report()
    html = body_html(app, report)
    assert '<p class="top-risk-meta">Programme Lead' in html


def test_headline_figures_carry_their_comparisons(app):
    report, _ = synthetic_report()
    h = report.headline
    text = flat_text(body_html(app, report))
    assert f"{fmt_rate(h.required_rate)} a week needed" in text
    assert f"Next week: {h.next_week_target}" in text
    assert h.weeks_left is not None and f"{h.weeks_left} weeks to {fmt_date(h.target_completion)}" in text
    dvt = h.forecast_vs_target_days
    assert f"{abs(dvt)} days {'after' if dvt > 0 else 'before'} target" in text


def test_data_check_warning_when_totals_differ(app):
    import dataclasses

    report, _ = synthetic_report()
    bad = dataclasses.replace(report, headline=dataclasses.replace(report.headline, totals_check_ok=False))
    assert "Data check: the tracker total does not match the sum of the groups." in body_html(app, bad)
    good = dataclasses.replace(report, headline=dataclasses.replace(report.headline, totals_check_ok=True))
    assert "Data check:" not in body_html(app, good)


def test_headline_figures_render_with_missing_values(app):
    import dataclasses

    report, _ = synthetic_report()
    sparse = dataclasses.replace(
        report,
        headline=dataclasses.replace(
            report.headline, weeks_left=None, required_rate=None, forecast_vs_target_days=None, next_week_target=None
        ),
    )
    text = flat_text(body_html(app, sparse))
    assert "No required rate" in text and "Next week: –" in text and "weeks to" not in text


def test_headline_figures_in_print_html(app):
    from tracker.report.render import render_print_html

    report, _ = synthetic_report()
    with app.app_context():
        html = render_print_html(report)
    assert "a week needed" in html and "Programme Lead" in html


def test_print_html_loads_no_chart_scripts(app):
    report, _ = synthetic_report()
    with app.test_request_context("/"):
        html = render_print_html(report)
    assert 'data-chart="remaining"' in html
    assert "<script" not in html


def test_tooltip_swatches_match_palette():
    css = (Path(__file__).resolve().parent.parent / "tracker" / "static" / "tracker.css").read_text(encoding="utf-8")
    for key in ("plan", "actual", "forecast"):
        assert re.search(rf"\.chart-swatch-{key}\s*{{[^}}]*background:\s*{PALETTE[key]}", css), key
