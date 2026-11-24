"""The report's new "Status at a glance" view: the view switch, the answer sentence and the answer card."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import unescape

import pytest
from test_report import WEEKS, seed

from tracker.engine.calc import Headline
from tracker.models import ReportInput
from tracker.report.build import build_report
from tracker.report.dashboard import answer_sentence, build_dashboard
from tracker.trackers.targets import record_target_change


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
