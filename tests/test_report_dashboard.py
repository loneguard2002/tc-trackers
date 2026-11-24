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

from tracker.engine.calc import Headline
from tracker.models import Group, ReportInput, Risk
from tracker.report.build import build_report
from tracker.report.dashboard import StatusWeek, answer_sentence, build_dashboard, build_tiles, summarise_statuses
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
        == "On course to finish on 11 Dec, a week before the 18 Dec target, though 30 behind plan."
    )


def test_sentence_counts_days_before_target():
    sentence = answer_sentence(headline(forecast_completion=date(2026, 12, 15)), TARGET, None)
    assert sentence == "On course to finish on 15 Dec, 3 days before the 18 Dec target."
    assert answer_sentence(headline(forecast_completion=date(2026, 12, 17)), TARGET, 0).startswith(
        "On course to finish on 17 Dec, 1 day before the 18 Dec target."
    )


def test_sentence_omits_behind_plan_when_not_behind():
    for behind in (None, 0, -4):
        assert "behind plan" not in answer_sentence(headline(), TARGET, behind)


def test_sentence_on_the_target_date():
    sentence = answer_sentence(headline(forecast_completion=TARGET), TARGET, 12)
    assert sentence == "On course to finish on 18 Dec, on the target date, though 12 behind plan."


def test_sentence_forecast_after_target():
    sentence = answer_sentence(headline(forecast_completion=date(2026, 1, 8).replace(year=2027)), TARGET, 30)
    assert sentence == "Forecast to finish on 8 Jan, 21 days after the 18 Dec target."


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


def test_the_export_routes_do_not_read_the_view(client, db, small_tracker, viewer, monkeypatch):
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
    assert all('class="answer-card' not in html for html in seen)


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
    early = build_dashboard(
        db, build_report(db, small_tracker, WEEKS[1], date(2026, 9, 14), with_charts=False), date(2026, 9, 14)
    )
    assert early.target == date(2026, 12, 11) and early.targets == []
    late = build_dashboard(
        db, build_report(db, small_tracker, WEEKS[3], date(2026, 9, 28), with_charts=False), date(2026, 9, 28)
    )
    assert late.target == date(2026, 12, 25) and len(late.targets) == 1


def test_behind_plan_comes_from_the_report_week(db, small_tracker):
    seed(db, small_tracker)
    report = build_report(db, small_tracker, WEEKS[1], date(2026, 9, 14), with_charts=False)
    row = next(r for r in report.rows if r.week_ending == WEEKS[1])
    behind = row.cum_target - row.cum_actual
    dashboard = build_dashboard(db, report, date(2026, 9, 14))
    assert (f"{behind} behind plan" in dashboard.answer) == (behind > 0)
    assert dashboard.tone == "none" and dashboard.needed is None and dashboard.written_by is None


# --- Tiles (no database) ---------------------------------------------------------------------------------------


def entry(number, day, kind="moved"):
    return TargetEntry(number, day, kind, date(2026, 10, 1), None, "", None, False)


def tiles_for(**overrides):
    target = overrides.pop("target", TARGET)
    targets = overrides.pop("targets", [])
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
    return build_tiles(report, target, targets)


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
    spark = build_tiles(report, None, [])["week"]["spark"]
    assert len(spark["points"].split()) == 2
    assert spark["last_x"] and spark["last_y"]


def test_rate_tile():
    tile = tiles_for()["rate"]
    assert (tile["value"], tile["sub"], tile["tone"]) == ("41.3", "31.3 a week needed", "success")
    assert 0 < float(tile["fill"]) <= 100 and 0 < float(tile["mark"]) <= 100
    assert float(tile["mark"]) < float(tile["fill"])
    slow = tiles_for(forecast_rate=20.0)["rate"]
    assert slow["tone"] == "danger" and float(slow["mark"]) > float(slow["fill"])
    none = tiles_for(required_rate=None)["rate"]
    assert none["sub"] == "No required rate" and none["mark"] is None
    assert tiles_for(forecast_rate=None)["rate"]["fill"] is None


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


def test_forecast_tile_lists_where_the_target_moved():
    first, second, third = date(2026, 12, 4), date(2026, 12, 11), TARGET
    assert tiles_for()["forecast"]["moved"] is None
    one = tiles_for(targets=[entry(1, first, "set"), entry(2, second)])["forecast"]["moved"]
    assert one == "Target moved once: 4 Dec → 11 Dec"
    two = tiles_for(targets=[entry(1, first, "set"), entry(2, second), entry(3, third)])["forecast"]["moved"]
    assert two == "Target moved twice: 4 Dec → 11 Dec → 18 Dec"
    three = tiles_for(targets=[entry(1, first), entry(2, second), entry(3, third), entry(4, TARGET)])["forecast"]
    assert three["moved"].startswith("Target moved 4 times: ")
    assert tiles_for(targets=[entry(1, first, "set")])["forecast"]["moved"] is None  # set once, never moved


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
    assert "Due 30 Sep" in flat and "Site A · Programme Lead" in flat
    assert re.search(r'glance-chip glance-chip-red">\s*<svg[^>]*>.*?</svg>\s*Red', html, re.S)


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
    early = build_tiles(report, date(2026, 8, 1), [])["forecast"]["timeline"]
    assert float(early["target"]) >= float(early["start"])
    past = replace(report, headline=replace(report.headline, forecast_completion=date(2026, 8, 1)))
    line = build_tiles(past, date(2026, 12, 18), [])["forecast"]["timeline"]
    assert float(line["forecast"]) >= float(line["start"])
    assert float(line["end"]) >= float(line["start"])
    both = build_tiles(past, date(2026, 7, 1), [])["forecast"]["timeline"]
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
