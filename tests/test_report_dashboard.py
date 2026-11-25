"""The report's new "Status at a glance" view: the view switch, the answer sentence and the answer card."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pytest
from report_helpers import synthetic_report
from test_report import WEEKS, seed

from tracker.engine.calc import IN_PROGRESS, Headline
from tracker.formatting import fmt_rate
from tracker.models import Group, ReportInput, Risk
from tracker.report.build import build_report
from tracker.report.dashboard import (
    StatusWeek,
    answer_sentence,
    build_dashboard,
    build_tiles,
    summarise_statuses,
    target_note,
)
from tracker.trackers.targets import TargetEntry, record_target_change


def headline(**overrides) -> Headline:
    values = dict.fromkeys(Headline.__dataclass_fields__)
    values.update(total_scope=500, completed=200, remaining=300, forecast_completion=date(2026, 12, 11))
    values.update(overrides)
    return Headline(**values)


# --- The sentence (no database) --------------------------------------------------------------------------------

TARGET = date(2026, 12, 18)


def test_sentence_when_everything_is_done():
    assert answer_sentence(headline(completed=500, remaining=0), TARGET, 0) == "All 500 done."


def test_sentence_forecast_before_target_and_behind_plan():
    assert (
        answer_sentence(headline(), TARGET, 30)
        == "On course to finish on 11 Dec,\na week before the 18 Dec target, though 30 behind plan."
    )


def test_sentence_counts_days_before_target():
    sentence = answer_sentence(headline(forecast_completion=date(2026, 12, 15)), TARGET, None)
    assert sentence == "On course to finish on 15 Dec,\n3 days before the 18 Dec target."
    assert answer_sentence(headline(forecast_completion=date(2026, 12, 17)), TARGET, 0).startswith(
        "On course to finish on 17 Dec,\n1 day before the 18 Dec target."
    )


def test_sentence_omits_behind_plan_when_not_behind():
    for behind in (None, 0, -4):
        assert "behind plan" not in answer_sentence(headline(), TARGET, behind)


def test_sentence_on_the_target_date():
    sentence = answer_sentence(headline(forecast_completion=TARGET), TARGET, 12)
    assert sentence == "On course to finish on 18 Dec,\non the target date, though 12 behind plan."


def test_sentence_forecast_after_target():
    sentence = answer_sentence(headline(forecast_completion=date(2026, 1, 8).replace(year=2027)), TARGET, 30)
    assert sentence == "Forecast to finish on 8 Jan,\n21 days after the 18 Dec target."


def test_sentence_without_a_target():
    assert answer_sentence(headline(), None, 30) == "Forecast to finish on 11 Dec. No target date is set."


def test_sentence_without_a_forecast():
    assert answer_sentence(headline(forecast_completion=None), TARGET, 30) == (
        "Not enough completed weeks to forecast yet."
    )
    assert answer_sentence(headline(forecast_completion=None), None, None) == (
        "Not enough completed weeks to forecast yet."
    )


def test_sentence_for_a_tracker_with_no_scope_is_not_finished():
    sentence = answer_sentence(headline(total_scope=0, completed=0, remaining=0, forecast_completion=None), None, None)
    assert sentence == "Not enough completed weeks to forecast yet."


# --- Database --------------------------------------------------------------------------------------------------


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1], target_completion=date(2026, 12, 25))


@pytest.fixture
def viewer(client, logged_in_user, grant, small_tracker):
    grant(logged_in_user, small_tracker, "viewer")
    return logged_in_user


def url(tracker, query=""):
    return f"/trackers/{tracker.id}/report{query}"


def text(response) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))).split())


def is_classic(response) -> bool:
    return 'data-chart="remaining"' in response.get_data(as_text=True)


def is_new(response) -> bool:
    return 'class="answer-card' in response.get_data(as_text=True)


def test_the_new_view_is_the_default_and_sets_the_session(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    response = client.get(url(small_tracker))
    assert response.status_code == 200 and is_new(response) and not is_classic(response)
    with client.session_transaction() as session:
        assert session["report_view"] == "new"


def test_classic_view_shows_todays_page_and_sticks_across_trackers(
    client, db, small_tracker, viewer, tracker_factory, grant
):
    seed(db, small_tracker)
    other = tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    grant(viewer, other, "viewer")
    response = client.get(url(small_tracker, "?view=classic"))
    assert is_classic(response) and not is_new(response)
    with client.session_transaction() as session:
        assert session["report_view"] == "classic"
    assert is_classic(client.get(url(other)))
    assert is_new(client.get(url(other, "?view=new")))
    assert is_new(client.get(url(small_tracker)))


def test_a_bad_view_value_is_ignored(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    client.get(url(small_tracker, "?view=classic"))
    for bad in ("other", "", "NEW", "classic%20"):
        assert is_classic(client.get(url(small_tracker, f"?view={bad}")))
    with client.session_transaction() as session:
        assert session["report_view"] == "classic"


def test_the_switch_shows_on_both_views_with_the_active_one_marked(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    week = WEEKS[1].isoformat()
    for query, active, other in (
        ("?view=new", "New view", "Classic view"),
        ("?view=classic", "Classic view", "New view"),
    ):
        html = client.get(url(small_tracker, f"{query}&week={week}")).get_data(as_text=True)
        links = re.findall(r'<a [^>]*href="([^"]*view=[^"]*)"([^>]*)>\s*([^<]*?)\s*</a>', html)
        assert [label for _, _, label in links] == ["New view", "Classic view"]
        current = [label for _, attrs, label in links if 'aria-current="page"' in attrs]
        assert current == [active] and other not in current
        assert all(f"week={week}" in href for href, _, _ in links)
        assert links[0][0].startswith(f"/trackers/{small_tracker.id}/report?view=new")
        assert links[1][0].startswith(f"/trackers/{small_tracker.id}/report?view=classic")


def test_the_downloads_and_data_ignore_the_session(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    for view in ("new", "classic"):
        client.get(url(small_tracker, f"?view={view}"))
        assert (
            client.get(f"/trackers/{small_tracker.id}/report/data.json?week={WEEKS[1].isoformat()}").status_code == 200
        )
        svg = client.get(f"/trackers/{small_tracker.id}/report/chart/remaining.svg?week={WEEKS[1].isoformat()}")
        assert svg.status_code == 200 and svg.mimetype == "image/svg+xml"


def test_the_export_routes_ignore_the_view_kept_for_the_page(client, db, small_tracker, viewer, monkeypatch):
    seen = []
    monkeypatch.setattr("tracker.report.views.html_to_pdf", lambda html: seen.append(html) or b"%PDF")
    monkeypatch.setattr("tracker.report.views.html_to_png", lambda html: seen.append(html) or b"PNG")
    seed(db, small_tracker)
    for view in ("new", "classic"):
        with client.session_transaction() as session:
            session["report_view"] = view
        assert client.get(f"/trackers/{small_tracker.id}/report.pdf?week={WEEKS[1].isoformat()}").data == b"%PDF"
        assert (
            client.get(f"/trackers/{small_tracker.id}/report.png?week={WEEKS[1].isoformat()}&view=new").data == b"PNG"
        )
    # The chart pictures carry a drawing timestamp, so compare the pages without them.
    plain = [re.sub(r"data:[^\"']+", "", html) for html in seen]
    assert len(seen) == 4 and plain[0] == plain[2] and plain[1] == plain[3]  # the same whichever view is kept
    # Only the link's own ?view=new asks for the new layout (the owner's call, after #81).
    assert 'class="answer-card' not in seen[0] and 'class="answer-card' in seen[1]


def test_a_viewer_sees_both_views(client, small_tracker, viewer):
    for view in ("new", "classic"):
        assert client.get(url(small_tracker, f"?view={view}")).status_code == 200


def test_the_answer_card_shows_status_sentence_headline_and_what_is_needed(
    client, db, small_tracker, viewer, user_factory
):
    seed(db, small_tracker)
    author = user_factory(full_name="A. Name")
    db.add(
        ReportInput(
            tracker_id=small_tracker.id,
            week_ending=WEEKS[1],
            status="Amber",
            headline="Slow week",
            decisions="Approve extra staff",
            prepared_by=author.id,
            updated_at=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    response = client.get(url(small_tracker, f"?view=new&week={WEEKS[1].isoformat()}"))
    flat = text(response)
    html = response.get_data(as_text=True)
    assert 'class="answer-card' in html and "answer-card-amber" in html
    assert re.search(r'class="[^"]*status-badge[^"]*"[^>]*>\s*<svg.*?</svg>\s*Amber\s*<', html, re.S)
    assert "Slow week" in flat
    assert "Needed from you Approve extra staff" in flat
    assert "Written by A. Name on 20 Nov 2026" in flat
    assert re.search(r"(On course|Forecast) to finish on \d+ \w+", flat) and "Dec target" in flat


def test_the_answer_card_without_an_update(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    flat = text(client.get(url(small_tracker, f"?view=new&week={WEEKS[1].isoformat()}")))
    assert "No weekly update written for this week." in flat
    assert "Needed from you None" in flat and "Written by" not in flat
    assert "Not set" in flat


def test_the_answer_card_on_an_empty_tracker(client, small_tracker, viewer):
    response = client.get(url(small_tracker, "?view=new"))
    assert response.status_code == 200 and "Not enough completed weeks to forecast yet." in text(response)


def test_build_dashboard_uses_the_target_in_force_in_the_report_week(db, small_tracker, user_factory):
    seed(db, small_tracker)
    # The target moved on 20 Sep 2026 (after week 2); the week 2 report still answers against the old one.
    record_target_change(db, small_tracker.id, date(2026, 12, 11), date(2026, 12, 25), None)
    db.flush()
    from sqlalchemy import select

    from tracker.models import TargetChange

    change = db.scalars(select(TargetChange).where(TargetChange.tracker_id == small_tracker.id)).one()
    change.changed_at = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    db.commit()
    early_report = build_report(db, small_tracker, WEEKS[1], date(2026, 9, 14), with_charts=False)
    early = build_dashboard(db, early_report, date(2026, 9, 14))
    # The target in place before the change was recorded stands as an unnumbered "set" entry.
    assert early.target == date(2026, 12, 11)
    assert [(e.date, e.kind, e.changed_on, e.current) for e in early.targets] == [
        (date(2026, 12, 11), "set", None, True)
    ]
    assert early.target_lines == [] and early.target_note == ""
    # The rate needed comes from that target (13 weeks from 11 Sep to 11 Dec), not today's 25 Dec one.
    needed = fmt_rate(early_report.headline.remaining / 13)
    assert early.tiles["rate"]["sub"] == f"{needed} a week needed"
    assert needed != fmt_rate(early_report.headline.required_rate)
    late = build_dashboard(
        db, build_report(db, small_tracker, WEEKS[3], date(2026, 9, 28), with_charts=False), date(2026, 9, 28)
    )
    assert late.target == date(2026, 12, 25) and len(late.targets) == 2
    assert late.target_note == "moved once, 14 days later than first set"
    assert [line.text for line in late.target_lines] == [
        "In place before changes were recorded.",
        "Moved on 20 Sep, 14 days later. No reason given.",
    ]


def test_behind_plan_comes_from_the_report_week(db, small_tracker):
    seed(db, small_tracker)
    report = build_report(db, small_tracker, WEEKS[1], date(2026, 9, 14), with_charts=False)
    row = next(r for r in report.rows if r.week_ending == WEEKS[1])
    behind = row.cum_target - row.cum_actual
    dashboard = build_dashboard(db, report, date(2026, 9, 14))
    assert (f"{behind} behind plan" in dashboard.answer) == (behind > 0)
    assert dashboard.tone == "none" and dashboard.needed is None and dashboard.written_by is None


MID_WEEK = date(2026, 9, 9)  # a Wednesday in the week ending 11 Sep


def test_behind_plan_in_a_week_in_progress_comes_from_the_last_complete_week(db, small_tracker):
    seed(db, small_tracker)  # 8 done in the week ending 4 Sep against 10; the week ending 11 Sep has just begun
    report = build_report(db, small_tracker, WEEKS[1], MID_WEEK, with_charts=False)
    assert report.in_progress
    answer = build_dashboard(db, report, MID_WEEK).answer
    assert answer.endswith(", though 2 behind plan.") and "12 behind plan" not in answer


def test_risks_in_a_week_in_progress_are_past_due_against_today(db, small_tracker):
    group = seed(db, small_tracker)
    make_risks(db, small_tracker, group)  # R1 was due on 8 Sep
    db.add(Risk(tracker_id=small_tracker.id, ref="R6", rag="Red", description="Soon", target_date=date(2026, 9, 10)))
    db.commit()
    report = build_report(db, small_tracker, WEEKS[1], MID_WEEK, with_charts=False)
    risks = {risk.ref: risk for risk in build_dashboard(db, report, MID_WEEK).risks}
    assert (risks["R1"].due, risks["R1"].past) == ("1 day past 8 Sep", True)
    assert (risks["R6"].due, risks["R6"].past) == ("Due 10 Sep", False)


def test_the_page_marks_a_week_in_progress(client, db, small_tracker, viewer, monkeypatch):
    monkeypatch.setattr("tracker.report.views.today", lambda: MID_WEEK)
    group = seed(db, small_tracker)
    from tracker.models import CompletionEntry

    db.add(
        CompletionEntry(
            tracker_id=small_tracker.id, group_id=group.id, quantity=3, entry_date=MID_WEEK, week_ending=WEEKS[1]
        )
    )
    db.commit()
    html = page(client, small_tracker)
    assert re.search(
        r'<section class="answer-card[^"]*".*?<div class="answer-badges">\s*'
        r'<span class="status-badge status-badge-\w+">.*?</span>'
        r'<span class="status-badge status-badge-progress">In progress</span>',
        html,
        re.S,
    )
    assert "3 so far of 10 target" in text_of(html)
    assert "In progress" not in page(client, small_tracker, WEEKS[0])


def test_the_view_is_written_to_the_session_only_when_it_changes(app):
    from flask import session

    from tracker.report.views import _chosen_view

    with app.test_request_context("/?view=classic"):
        session["report_view"] = "classic"
        session.modified = False
        assert _chosen_view() == "classic" and not session.modified
    with app.test_request_context("/"):
        session["report_view"] = "new"
        session.modified = False
        assert _chosen_view() == "new" and not session.modified
    with app.test_request_context("/?view=classic"):
        assert _chosen_view() == "classic" and session["report_view"] == "classic" and session.modified
    with app.test_request_context("/"):
        assert _chosen_view() == "new" and session["report_view"] == "new"


# --- Tiles (no database) ---------------------------------------------------------------------------------------


def entry(number, day, kind="moved"):
    return TargetEntry(number, day, kind, date(2026, 10, 1), None, "", None, False)


def tiles_for(**overrides):
    target = overrides.pop("target", TARGET)
    report, _ = synthetic_report()
    values = dict(
        completed=375,
        total_scope=500,
        pct_complete=0.75,
        remaining=125,
        this_week_actual=42,
        this_week_target=40,
        next_week_target=40,
        forecast_rate=41.3,
        required_rate=31.3,
        forecast_completion=date(2026, 12, 11),
    )
    values.update(overrides)
    report = replace(report, headline=replace(report.headline, **values))
    return build_tiles(report, target)


def test_completed_tile():
    tile = tiles_for()["completed"]
    assert (tile["value"], tile["unit"], tile["sub"]) == ("375", "of 500", "75% · 125 left")
    assert tile["pct"] == "75.00"


def test_this_week_tile_against_target():
    assert tiles_for()["week"]["sub"] == "+2 against target · next week 40"
    assert tiles_for()["week"]["tone"] == "success"
    assert tiles_for(this_week_actual=40)["week"]["sub"].startswith("On target")
    behind = tiles_for(this_week_actual=37)["week"]
    assert behind["sub"] == "−3 against target · next week 40" and behind["tone"] == "danger"
    assert tiles_for(this_week_target=None)["week"]["sub"] == "No target for this week"
    assert tiles_for(next_week_target=None)["week"]["sub"] == "+2 against target"


def test_this_week_sparkline_covers_the_weeks_up_to_the_report_week():
    report, _ = synthetic_report()  # report week is the second of four; two weeks have actuals
    spark = build_tiles(report, None)["week"]["spark"]
    assert len(spark["points"].split()) == 2
    assert spark["last_x"] and spark["last_y"]


def test_this_week_tile_in_a_week_in_progress_says_so_far():
    report, _ = synthetic_report(in_progress=True)
    report = replace(report, headline=replace(report.headline, this_week_actual=28, this_week_target=40))
    week = build_tiles(report, TARGET)["week"]
    assert (week["value"], week["unit"]) == ("28", "so far of 40 target")
    assert week["sub"] == "12 to go · next week 10" and week["tone"] == ""
    ahead = replace(report, headline=replace(report.headline, this_week_actual=42, this_week_target=40))
    assert build_tiles(ahead, TARGET)["week"]["sub"] == "+2 against target · next week 10"
    unplanned = replace(report, headline=replace(report.headline, this_week_actual=28, this_week_target=None))
    assert build_tiles(unplanned, TARGET)["week"]["unit"] == "so far"


def test_this_week_sparkline_leaves_out_the_week_in_progress():
    report, _ = synthetic_report()
    rows = list(report.rows)
    rows[1] = replace(rows[1], state=IN_PROGRESS)
    spark = build_tiles(replace(report, rows=rows), None)["week"]["spark"]
    assert len(spark["points"].split()) == 1


# The synthetic report week ends on 11 Sep; a 9 Oct target leaves 4 weeks.
FOUR_WEEKS = date(2026, 10, 9)


def test_rate_tile():
    tile = tiles_for(target=FOUR_WEEKS, remaining=124)["rate"]
    assert (tile["value"], tile["sub"], tile["tone"]) == ("41.3", "31.0 a week needed", "success")
    assert 0 < float(tile["fill"]) <= 100 and 0 < float(tile["mark"]) <= 100
    assert float(tile["mark"]) < float(tile["fill"])
    slow = tiles_for(target=FOUR_WEEKS, remaining=124, forecast_rate=20.0)["rate"]
    assert slow["tone"] == "danger" and float(slow["mark"]) > float(slow["fill"])
    none = tiles_for(target=None)["rate"]
    assert none["sub"] == "No required rate" and none["mark"] is None
    assert tiles_for(forecast_rate=None)["rate"]["fill"] is None


def test_rate_tile_needs_the_target_given_not_the_headline_one():
    # The headline's own rate (31.3) is for today's target; the tile works from the target it is given.
    assert tiles_for(target=date(2026, 10, 2), remaining=120)["rate"]["sub"] == "40.0 a week needed"  # 3 weeks
    assert tiles_for(target=date(2026, 9, 14), remaining=120)["rate"]["sub"] == "120.0 a week needed"  # part week
    for passed in (date(2026, 9, 11), date(2026, 9, 1)):
        assert tiles_for(target=passed)["rate"]["sub"] == "No required rate"


def test_forecast_tile_against_the_target():
    early = tiles_for()["forecast"]
    assert early["value"] == "11 Dec" and early["sub"] == "7 days before the 18 Dec target"
    assert early["tone"] == "success"
    late = tiles_for(forecast_completion=date(2026, 12, 19))["forecast"]
    assert late["sub"] == "1 day after the 18 Dec target" and late["tone"] == "danger"
    assert tiles_for(forecast_completion=TARGET)["forecast"]["sub"] == "On the target date"
    assert tiles_for(target=None)["forecast"]["sub"] == "No target date"
    assert tiles_for(forecast_completion=None)["forecast"]["sub"] == "No forecast yet"
    assert tiles_for(forecast_completion=None)["forecast"]["value"] == "–"


def test_forecast_tile_does_not_list_where_the_target_moved(client, db, small_tracker, viewer):
    # The owner's call: the moves are on the chart and in "Target date changes", not on the tile.
    from report_helpers import add_target_change

    seed(db, small_tracker)
    add_target_change(
        db, small_tracker, date(2026, 12, 18), date(2026, 12, 25), datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
    )
    html = page(client, small_tracker)
    assert "Target date changes" in html and "Target moved" not in html
    assert "moved" not in tiles_for()["forecast"]


def test_target_note_says_back_to_the_first_date_only_when_it_is():
    first = date(2026, 12, 4)
    later = [entry(1, first, "set"), entry(2, first + timedelta(days=7))]
    assert target_note(later) == "moved once, 7 days later than first set"
    assert target_note([*later, entry(3, first)]) == "moved twice, back to the date first set"
    assert target_note([entry(1, first, "set")]) == ""


# --- Status summary (no database) ------------------------------------------------------------------------------


def weeks_of(*statuses):
    start = date(2026, 9, 4)
    return [StatusWeek(start + timedelta(days=7 * i), s) for i, s in enumerate(statuses)]


def test_summary_streak_and_red_weeks():
    weeks = weeks_of("Green", "Red", "Amber", "Amber", "Amber")  # Red on 11 Sep
    assert summarise_statuses(weeks) == "Amber for 3 weeks; Red once, on 11 Sep."
    assert summarise_statuses(weeks_of("Green", "Green", "Green", "Green", "Green")) == "Green for 5 weeks."
    assert summarise_statuses(weeks_of("Green")) == "Green for 1 week."


def test_summary_red_counts_and_dashes_break_streaks():
    assert summarise_statuses(weeks_of("Red", "Green", "Red", "Green", "Red", None)).startswith("Red 3 times")
    assert (
        summarise_statuses(weeks_of("Red", None, "Red", "Green")) == "Green for 1 week; Red twice, on 4 Sep and 18 Sep."
    )
    assert summarise_statuses(weeks_of("Green", "Green", None, "Green")) == "Green for 1 week."


def test_summary_when_the_streak_is_red_names_the_earlier_red_weeks():
    assert summarise_statuses(weeks_of("Green", "Red", "Red")) == "Red for 2 weeks."
    assert summarise_statuses(weeks_of("Red", "Green", "Red")) == "Red for 1 week; Red once before, on 4 Sep."
    assert summarise_statuses(weeks_of("Red", "Green", "Red", "Red")) == "Red for 2 weeks; Red once before, on 4 Sep."
    assert summarise_statuses(weeks_of("Red", None, "Red", "Green", "Red")) == (
        "Red for 1 week; Red twice before, on 4 Sep and 18 Sep."
    )
    assert summarise_statuses(weeks_of("Red", "Red", "Red", "Green", "Red", "Red")) == (
        "Red for 2 weeks; Red 3 times before."
    )


def test_summary_when_nothing_is_set():
    assert summarise_statuses(weeks_of(None, None)) == "No statuses yet."
    assert summarise_statuses([]) == "No statuses yet."
    assert summarise_statuses(weeks_of("Green", None)) == "No status for the report week."


# --- The page --------------------------------------------------------------------------------------------------


def page(client, tracker, week=None):
    week = (week or WEEKS[1]).isoformat()
    return client.get(url(tracker, f"?view=new&week={week}")).get_data(as_text=True)


def test_the_page_shows_the_four_tiles(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    html = page(client, small_tracker)
    flat = text_of(html)
    for label in ("Completed", "This week", "Rate", "Forecast"):
        assert re.search(rf'class="glance-tile-label"[^>]*>\s*{label}', html)
    assert "20 of 100" in flat and "20% · 80 left" in flat
    assert 'width="20.00"' in html
    assert "12 of 10 target" in flat and "+2 against target · next week 10" in flat
    assert html.count('class="glance-tile ') == 4


def text_of(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_the_status_strip_marks_the_report_week_and_summarises(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    for week, status in ((WEEKS[0], "Red"), (WEEKS[1], "Amber"), (WEEKS[3], "Green")):  # after the report week
        db.add(
            ReportInput(
                tracker_id=small_tracker.id, week_ending=week, status=status, updated_at=datetime.now(timezone.utc)
            )
        )
    db.commit()
    html = page(client, small_tracker)
    squares = re.findall(
        r'<li class="glance-strip-week glance-strip-(\w+)( is-report)?"[^>]*>'
        r'\s*<span class="glance-strip-letter">(.)</span>'
        r'\s*<span class="glance-strip-day">(\d+)</span>',
        html,
    )
    assert [(tone, letter, day) for tone, _, letter, day in squares] == [("red", "R", "4"), ("amber", "A", "11")]
    assert [bool(mark) for _, mark, _, _ in squares] == [False, True]
    flat = text_of(html)
    assert "Status, last 12 weeks" in flat and "Amber for 1 week; Red once, on 4 Sep." in flat


def test_the_status_strip_with_no_statuses(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    flat = text_of(page(client, small_tracker))
    assert "No statuses yet." in flat
    assert re.search(r'glance-strip-none[^>]*>\s*<span class="glance-strip-letter">–<', page(client, small_tracker))


def test_the_status_strip_shows_at_most_twelve_weeks(client, db, tracker_factory, grant, logged_in_user):
    first = date(2026, 1, 2)
    weeks = [first + timedelta(days=7 * i) for i in range(15)]
    tracker = tracker_factory(first_week_ending=weeks[0], last_week_ending=weeks[-1])
    grant(logged_in_user, tracker, "viewer")
    html = client.get(url(tracker, f"?view=new&week={weeks[-1].isoformat()}")).get_data(as_text=True)
    assert html.count('class="glance-strip-week ') == 12


def make_risks(db, tracker, group):
    rows = (
        ("R1", "Red", "Power cut", date(2026, 9, 8), "Open"),  # past the report week (11 Sep) by 3 days
        ("R2", "Amber", "Late kit", date(2026, 9, 30), "In progress"),
        ("R3", "Green", "Minor", None, "Open"),
        ("R4", "Green", "Extra one", None, "Open"),
        ("R5", "Green", "Closed one", None, "Closed"),
    )
    for ref, rag, description, due, status in rows:
        db.add(
            Risk(
                tracker_id=tracker.id,
                ref=ref,
                rag=rag,
                description=description,
                target_date=due,
                status=status,
                owner_role="Programme Lead",
                group_id=group.id,
            )
        )
    db.commit()


def test_top_risks_card(client, db, small_tracker, viewer):
    group = seed(db, small_tracker)
    make_risks(db, small_tracker, group)
    html = page(client, small_tracker)
    flat = text_of(html)
    assert "Top risks 3 of 4 open" in flat
    assert "R1 Power cut" in flat and "R2 Late kit" in flat and "R4 Extra one" not in flat
    assert re.search(r'<span class="tone-danger">3 days past 8 Sep</span>', html)
    assert "Due 30 Sep" in flat
    assert re.search(r'glance-chip glance-chip-red">\s*<svg[^>]*>.*?</svg>\s*Red', html, re.S)
    # A standard table: sortable headings, a row per risk with its location and owner in their own cells.
    table = re.search(r'<table id="glance-risks-table"[^>]*data-sortable[^>]*>(.*?)</table>', html, re.S).group(1)
    headings = re.findall(r'data-sort="(\w+)"', table)
    assert headings == ["rag", "risk", "due", "location", "owner"]
    rows = re.findall(r"<tr data-sort-rag[^>]*>(.*?)</tr>", table, re.S)
    assert len(rows) == 3
    assert '<td data-label="Location:">Site A</td>' in rows[0]
    assert '<td data-label="Owner:">Programme Lead</td>' in rows[0]
    assert re.search(r'<tr data-sort-rag="3" data-sort-risk="R1" data-sort-due="2026-09-08"', table)


def test_the_new_view_heads_the_report_with_the_week_and_the_labels(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    html = page(client, small_tracker)
    title = re.search(r'<div class="report-title glance-title">(.*?)</div>', html, re.S).group(1)
    assert "<h2>Week ending 11 Sep 2026</h2>" in title
    assert re.search(r'<p class="report-meta">[^<]+ · [^<]+</p>', title)


def test_top_risks_card_without_risks(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    flat = text_of(page(client, small_tracker))
    assert "Top risks 0 of 0 open" in flat and "No open risks." in flat


def test_locations_are_live_ones_furthest_behind_first(client, db, small_tracker, viewer):
    first = seed(db, small_tracker)  # Site A: 20 of 100
    first.starting_completed = 5
    db.add(Group(tracker_id=small_tracker.id, name="Site B", baseline=160, sort_order=2, starting_completed=0))
    db.add(Group(tracker_id=small_tracker.id, name="Site C", baseline=10, sort_order=3, retired=True))
    db.commit()
    html = page(client, small_tracker)
    flat = text_of(html)
    assert "Locations, furthest behind first" in flat
    names = re.findall(r'class="glance-location-name">([^<]+)<', html)
    assert names == ["Site B", "Site A"]  # 0% then 25%; the retired one is left out
    assert "25 of 100 · 25%" in flat
    assert "75 left · 5 done before the first week" in flat
    assert "Done before the first week" in flat and "Done since" in flat
    assert "Not shown: 1 retired location" in flat
    assert re.search(r'class="bar-start"', html)


def test_locations_with_none(client, db, small_tracker, viewer):
    flat = text_of(page(client, small_tracker))
    assert "Locations, furthest behind first" in flat and "No locations yet." in flat


def test_the_chart_section_has_its_title_subtitle_and_picture(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    small_tracker.unit_label = "devices"
    db.commit()
    html = page(client, small_tracker)
    assert re.search(r'<section[^>]*id="glance-chart"[^>]*>.*?<h2[^>]*>Remaining</h2>', html, re.S)
    assert 'class="report-glance' in html
    assert "Devices left to do, by week ending" in text_of(html)
    week = WEEKS[1].isoformat()
    assert re.search(
        rf'<img[^>]*data-chart="remaining-glance"[^>]*src="/trackers/{small_tracker.id}/report/chart/remaining-glance.svg\?week={week}"',
        html,
    )
    assert f'data-chart-data="/trackers/{small_tracker.id}/report/data.json?week={week}"' in html
    assert "report-charts.js" in html and "echarts-6.1.0.min.js" in html


def test_the_chart_subtitle_falls_back_to_units(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    small_tracker.unit_label = ""
    db.commit()
    assert "Units left to do, by week ending" in text_of(page(client, small_tracker))


def _history(db, tracker):
    from report_helpers import add_target_change

    first, second, third = date(2026, 12, 4), date(2026, 12, 11), date(2026, 12, 18)
    add_target_change(db, tracker, None, first, datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    add_target_change(db, tracker, first, second, datetime(2026, 9, 3, 9, tzinfo=timezone.utc), "Kit delayed")
    add_target_change(db, tracker, second, third, datetime(2026, 9, 10, 9, tzinfo=timezone.utc))


def test_the_target_changes_list(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    _history(db, small_tracker)
    html = page(client, small_tracker)
    assert "Target date changes" in html
    flat = text_of(html)
    assert "moved twice, 14 days later than first set" in flat
    assert "Set on 1 Sep." in flat
    assert "Moved on 3 Sep, 7 days later: Kit delayed." in flat
    assert "Moved on 10 Sep, 7 days later. No reason given." in flat
    assert "Earlier targets are the faint numbered lines. Hover a week for its figures." in flat
    items = re.findall(r'<li class="glance-target(?: is-current)?">(.*?)</li>', html, re.S)
    assert len(items) == 3
    assert "<s>" in items[0] and "<s>" in items[1] and "<s>" not in items[2]  # earlier dates are struck through
    assert "glance-target-badge is-current" in html and html.count("glance-target-badge") >= 3


def test_the_target_changes_list_for_a_past_week_stops_at_that_week(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    _history(db, small_tracker)
    html = page(client, small_tracker, WEEKS[0])  # 4 Sep: only the first two changes were made
    flat = text_of(html)
    assert "moved once, 7 days later than first set" in flat
    assert len(re.findall(r'<li class="glance-target(?: is-current)?">', html)) == 2


def test_no_target_history_means_no_list(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    flat = text_of(page(client, small_tracker))
    assert "Target date changes" not in flat and "Earlier targets" not in flat


def test_a_removed_target_is_listed(client, db, small_tracker, viewer):
    from report_helpers import add_target_change

    seed(db, small_tracker)
    add_target_change(db, small_tracker, None, date(2026, 12, 4), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    add_target_change(db, small_tracker, date(2026, 12, 4), None, datetime(2026, 9, 2, 9, tzinfo=timezone.utc))
    flat = text_of(page(client, small_tracker))
    assert "Target removed on 2 Sep." in flat and "moved once" not in flat and "moved twice" not in flat


def test_a_tracker_without_a_target_has_no_forecast_target_text(client, db, tracker_factory, grant, logged_in_user):
    tracker = tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1], target_completion=None)
    grant(logged_in_user, tracker, "viewer")
    seed(db, tracker)
    html = page(client, tracker)
    assert response_ok(html) and "Target moved" not in html and "against the" not in text_of(html)


def response_ok(html: str) -> bool:
    return "glance-tile" in html


def test_timeline_never_draws_backwards():
    report, _ = synthetic_report()  # report week 11 Sep 2026
    early = build_tiles(report, date(2026, 8, 1))["forecast"]["timeline"]
    assert float(early["target"]) >= float(early["start"])
    past = replace(report, headline=replace(report.headline, forecast_completion=date(2026, 8, 1)))
    line = build_tiles(past, date(2026, 12, 18))["forecast"]["timeline"]
    assert float(line["forecast"]) >= float(line["start"])
    assert float(line["end"]) >= float(line["start"])
    both = build_tiles(past, date(2026, 7, 1))["forecast"]["timeline"]
    assert float(both["end"]) >= float(both["start"])


def test_new_styles_are_scoped_to_the_glance_view():
    css = (Path(__file__).parent.parent / "tracker" / "static" / "tracker.css").read_text()
    block = css[css.index("/* Status at a glance, below the answer card") :]
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    selectors = [sel.strip() for head in re.findall(r"([^{}]+)\{", block) for sel in head.split(",")]
    assert selectors
    for sel in selectors:
        if sel.startswith("@media"):
            continue
        assert re.match(r'(\[data-theme="dark"\] )?\.(report-glance|glance-)', sel), sel


def test_a_lone_set_has_no_list_and_a_move_brings_it_back(client, db, small_tracker, viewer):
    from report_helpers import add_target_change

    seed(db, small_tracker)
    add_target_change(db, small_tracker, None, date(2026, 12, 4), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    html = page(client, small_tracker)
    assert "Target date changes" not in html and "glance-target-badge" not in html
    add_target_change(
        db, small_tracker, date(2026, 12, 4), date(2026, 12, 11), datetime(2026, 9, 2, 9, tzinfo=timezone.utc)
    )
    assert "Target date changes" in page(client, small_tracker)


def test_the_first_move_of_a_target_set_before_recording_began(client, db, small_tracker, viewer):
    from report_helpers import add_target_change

    seed(db, small_tracker)  # the target, 25 Dec, was set before changes were recorded
    add_target_change(
        db, small_tracker, date(2026, 12, 18), date(2026, 12, 25), datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
    )
    html = page(client, small_tracker)
    flat = text_of(html)
    assert "Target date changes moved once, 7 days later than first set" in flat
    assert "back to the date first set" not in flat
    items = re.findall(r'<li class="glance-target(?: is-current)?">(.*?)</li>', html, re.S)
    assert len(items) == 2
    assert "<s>18 Dec</s>" in items[0] and "In place before changes were recorded." in items[0]
    assert "<s>" not in items[1] and "Moved on 9 Sep, 7 days later. No reason given." in text_of(items[1])
    assert "Target moved" not in flat
    # The week before the change answers against the date in place then, with no list.
    before = page(client, small_tracker, WEEKS[0])
    assert "Target date changes" not in before and "18 Dec target" in text_of(before)


def test_a_reason_is_shown_as_text(client, db, small_tracker, viewer):
    from report_helpers import add_target_change

    seed(db, small_tracker)
    add_target_change(db, small_tracker, None, date(2026, 12, 4), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    reason = '<img src=x onerror="alert(1)"> & <b>late</b>'
    add_target_change(
        db, small_tracker, date(2026, 12, 4), date(2026, 12, 11), datetime(2026, 9, 2, 9, tzinfo=timezone.utc), reason
    )
    html = page(client, small_tracker)
    assert "<img src=x" not in html and "<b>late</b>" not in html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt; &amp; &lt;b&gt;late&lt;/b&gt;" in html


# --- The PDF and PNG in the new layout ------------------------------------------------------------------------------


def exported(client, monkeypatch, tracker, extension, query=""):
    """The document the PDF or PNG route would convert, caught before Chromium runs."""
    seen = {}
    name = "html_to_pdf" if extension == "pdf" else "html_to_png"
    monkeypatch.setattr(f"tracker.report.views.{name}", lambda html: seen.setdefault("html", html) and b"x")
    response = client.get(f"/trackers/{tracker.id}/report.{extension}?week={WEEKS[1].isoformat()}{query}")
    assert response.status_code == 200
    return seen["html"]


@pytest.mark.parametrize("extension", ["pdf", "png"])
def test_the_new_view_downloads_its_own_layout(client, db, small_tracker, viewer, monkeypatch, extension):
    seed(db, small_tracker)
    html = exported(client, monkeypatch, small_tracker, extension, "&view=new")
    assert '<div class="report-glance report-dashboard">' in html and '<section class="report-band' not in html
    assert f"<h1>{small_tracker.name}: week ending 11 Sep 2026</h1>" in html
    # Self-contained: the Remaining chart drawn in, no scripts, no live chart data, nothing fetched.
    assert 'data-chart="remaining-glance"' in html and "data:image/svg+xml" in html
    assert "<script" not in html and "data-chart-data=" not in html and "report.chart_image" not in html
    assert not re.search(r'(?:src|href)\s*=\s*["\'](?:https?:)?/', html)
    assert "Hover a week" not in html  # nothing to hover on paper


def test_downloads_without_the_view_stay_classic_whatever_the_page_shows(
    client, db, small_tracker, viewer, monkeypatch
):
    seed(db, small_tracker)
    page(client, small_tracker)  # the person's report view is now the new one
    html = exported(client, monkeypatch, small_tracker, "pdf")
    assert '<section class="report-band' in html and '<div class="report-glance' not in html
    assert '<div class="report-glance' not in exported(client, monkeypatch, small_tracker, "pdf", "&view=classic")


def test_each_view_links_its_downloads_to_its_layout(client, db, small_tracker, viewer):
    seed(db, small_tracker)
    week = WEEKS[1].isoformat()
    new = page(client, small_tracker)
    assert f"report.pdf?week={week}&amp;view=new" in new and f"report.png?week={week}&amp;view=new" in new
    classic = client.get(url(small_tracker, f"?view=classic&week={week}")).get_data(as_text=True)
    assert f'report.pdf?week={week}"' in classic and f'report.png?week={week}"' in classic
