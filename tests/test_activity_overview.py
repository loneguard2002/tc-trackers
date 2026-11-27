"""Activity › Overview: the rules (no database) and the page (database required)."""

import html
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import sign_in
from tracker.activity import overview as ov
from tracker.activity.kinds import KIND_ACTIONS, KIND_LABELS, NOT_CHANGES, kind_of
from tracker.activity.scope import ACTION_AREAS
from tracker.models import AppSetting, AuditLog, CompletionEntry, Group

URL = "/admin/activity/overview"
LOG = "/admin/activity"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)  # a Thursday; the week ends on Friday 27 November
EARLY = datetime(2026, 9, 1, tzinfo=timezone.utc)


# --- Rules ---------------------------------------------------------------------------------------------------------


def test_weeks_end_on_friday():
    assert ov.week_end(date(2026, 11, 27)) == date(2026, 11, 27)  # Friday
    assert ov.week_end(date(2026, 11, 28)) == date(2026, 12, 4)  # Saturday starts the next week
    assert ov.week_end(date(2026, 11, 23)) == date(2026, 11, 27)  # Monday


def test_a_trackers_own_week_ending_inside_the_dashboard_week():
    friday = date(2026, 11, 27)
    assert ov.tracker_week(friday, 4) == friday
    assert ov.tracker_week(friday, 0) == date(2026, 11, 23)  # Monday
    assert ov.tracker_week(friday, 5) == date(2026, 11, 21)  # Saturday, the first day of the week


def test_update_status_by_the_end_of_the_week_ending_day():
    week = date(2026, 11, 20)
    end = datetime(2026, 11, 21, tzinfo=timezone.utc)
    assert ov.update_status(end - timedelta(seconds=1), week, NOW) == "done"
    assert ov.update_status(end, week, NOW) == "late"
    assert ov.update_status(None, week, NOW) == "missed"
    assert ov.update_status(None, date(2026, 11, 27), NOW) == "due"


def test_every_action_but_sign_ins_has_exactly_one_kind():
    for action in ACTION_AREAS:
        holding = [key for key, actions in KIND_ACTIONS.items() if action in actions]
        assert holding == ([] if action in NOT_CHANGES else [kind_of(action)]), action
    assert set(KIND_ACTIONS) == set(KIND_LABELS)
    assert kind_of("risk_updated") == "risks" and kind_of("inputs_saved") == "updates"
    assert kind_of("recipient_domains_changed") == "other" and kind_of("recipient_added") == "email"
    assert kind_of("team_renamed") == "people" and kind_of("region_created") == "lists"


@pytest.mark.parametrize(
    ("maximum", "top", "step"), [(0, 1, 1), (7, 8, 2), (37, 40, 10), (40, 50, 10), (380, 400, 100)]
)
def test_axis_top_is_round_and_above_the_tallest_bar(maximum, top, step):
    assert ov._nice_top(maximum) == (top, step)


# --- The page ------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(ov, "utcnow", lambda: NOW)


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def add(db, **kw) -> AuditLog:
    values = {"action": "entry_created", "entity": "entry", "entity_id": "1", "at": NOW - timedelta(hours=1)}
    values.update(kw)
    row = AuditLog(**values)
    db.add(row)
    db.commit()
    return row


def kpi(body: str, label: str) -> str:
    match = re.search(rf'act-kpi-label">{label}</span>\s*<span class="act-kpi-value">([^<]*)', body)
    assert match, label
    return match.group(1)


def test_overview_needs_view_activity(client, logged_in_user):
    assert client.get(URL).status_code == 403


def test_menu_opens_the_overview_and_both_views_have_tabs(client, logged_in_admin):
    body = text_of(client.get(URL))
    assert 'href="/admin/activity/overview"' in body and 'data-label="Activity"' in body
    assert re.search(r'<a class="tab active" href="/admin/activity/overview" aria-current="page">Overview</a>', body)
    log = text_of(client.get(LOG))
    assert re.search(r'<a class="tab active" href="/admin/activity" aria-current="page">Log</a>', log)


def test_headline_figures_and_the_comparison(client, logged_in_admin, db, user_factory):
    a, b = user_factory(), user_factory()
    for _ in range(3):
        add(db, user_id=a.id)
    add(db, user_id=b.id, action="login", entity="user")
    add(db, user_id=b.id, action="login_failed", entity="user")  # neither a sign-in nor a change
    add(db, action="report_sent", entity="report")  # written by the app: not a change
    add(db, user_id=a.id, at=NOW - timedelta(weeks=13))  # the 12 weeks before
    body = text_of(client.get(URL))
    assert kpi(body, "Changes made") == "3"
    assert kpi(body, "Sign-ins") == "1"
    assert kpi(body, "People active") == "2"  # the administrator signed in without an entry, so is not counted
    assert "+2 on the 12 weeks before" in body  # changes: 3 now, 1 before
    assert "made 3 changes" in body


def test_period_choices_and_unknown_values_fall_back(client, logged_in_admin, db, user_factory):
    a = user_factory()
    add(db, user_id=a.id, at=NOW - timedelta(weeks=20))
    assert kpi(text_of(client.get(URL)), "Changes made") == "0"
    body = text_of(client.get(URL + "?period=26"))
    assert kpi(body, "Changes made") == "1"
    assert 'aria-current="true">6 months</a>' in body
    assert 'aria-current="true">12 weeks</a>' in text_of(client.get(URL + "?period=7&metric=nope"))


def test_heatmap_squares_link_to_their_day_and_stop_at_today(client, logged_in_admin, db, user_factory):
    a = user_factory()
    add(db, user_id=a.id, at=datetime(2026, 11, 17, 9, tzinfo=timezone.utc))  # a quarter of the busiest day: lightest
    for _ in range(5):
        add(db, user_id=a.id, at=datetime(2026, 11, 19, 9, tzinfo=timezone.utc))
    body = text_of(client.get(URL))
    assert (
        'href="/admin/activity?from=2026-11-19&to=2026-11-19" aria-label="Thu 19 Nov 2026: 5 changes" '
        'data-detail="Thu 19 Nov 2026: 5 changes, 83% of the changes in the week ending 20 Nov."><rect class="heat-4"'
    ) in body
    assert (
        'aria-label="Tue 17 Nov 2026: 1 change" '
        'data-detail="Tue 17 Nov 2026: 1 change, 17% of the changes in the week ending 20 Nov."><rect class="heat-1"'
        in body
    )
    assert 'aria-label="Thu 26 Nov 2026: no changes so far"' in body
    assert "Fri 27 Nov 2026" not in body  # tomorrow has no square
    assert "Busiest day: Thu 19 Nov 2026, 5 changes. Thursday has 83% of the year’s changes." in body
    assert body.count('class="heat-day"') == 52 * 7 + 4  # 52 full weeks and Monday to Thursday of this one


def test_weekly_updates_by_tracker(client, logged_in_admin, db, tracker_factory):
    steady = tracker_factory(name="Steady", created_at=EARLY)
    lapsed = tracker_factory(name="Lapsed", created_at=EARLY)
    add(
        db,
        tracker_id=steady.id,
        action="inputs_saved",
        entity="report_input",
        entity_id="2026-11-20",
        at=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
    )
    add(
        db,
        tracker_id=steady.id,
        action="inputs_saved",
        entity="report_input",
        entity_id="2026-11-13",
        at=datetime(2026, 11, 16, 10, tzinfo=timezone.utc),
    )
    group = Group(tracker_id=lapsed.id, name="Site A", baseline=10)
    db.add(group)
    db.flush()
    db.add(
        CompletionEntry(
            tracker_id=lapsed.id,
            group_id=group.id,
            entry_date=date(2026, 11, 12),
            week_ending=date(2026, 11, 13),
            quantity=2,
            created_at=datetime(2026, 11, 12, 9, tzinfo=timezone.utc),
        )
    )
    db.commit()
    body = text_of(client.get(URL))
    assert "Week ending 20 Nov: updated by the week’s end" in body
    assert "Week ending 13 Nov: updated late" in body
    assert "Week ending 6 Nov: not updated" in body
    assert "Week ending 27 Nov: still due" in body
    assert "1 tracker missed the update for the week ending 20 Nov: Lapsed." in body
    # The tracker that missed last week comes first, its last-week square marked.
    assert body.index(">Lapsed</a>") < body.index(">Steady</a>")
    assert body.count("is-missed is-alert") == 1
    assert "Week to 13 Nov" in body  # Lapsed's last update came from its entry
    assert "1 tracker missed last week’s update" in body


def test_weeks_before_a_tracker_existed_are_not_counted(client, logged_in_admin, db, tracker_factory):
    tracker_factory(name="New", created_at=datetime(2026, 11, 18, tzinfo=timezone.utc))
    body = text_of(client.get(URL))
    assert "Week ending 13 Nov: not tracked that week" in body
    assert "Week ending 20 Nov: not updated" in body


def test_a_viewer_sees_figures_for_their_own_trackers_only(client, db, user_factory, tracker_factory, give_set, grant):
    viewer = user_factory()
    give_set(["view_activity"], user=viewer)
    mine = tracker_factory(name="Mine", created_at=EARLY)
    other = tracker_factory(name="Theirs", created_at=EARLY)
    grant(viewer, mine, "editor")
    someone = user_factory()
    add(db, user_id=someone.id, tracker_id=mine.id)
    for _ in range(4):
        add(db, user_id=someone.id, tracker_id=other.id)
    sign_in(client, viewer)
    body = text_of(client.get(URL))
    assert kpi(body, "Changes made") == "1"
    assert ">Mine</a>" in body and ">Theirs</a>" not in body


def test_who_and_what_changed_link_to_the_filtered_log(client, logged_in_admin, db, user_factory):
    a = user_factory(full_name="Priya Shah")
    add(db, user_id=a.id, action="risk_updated", entity="risk")
    add(db, user_id=a.id, action="risk_created", entity="risk")
    body = text_of(client.get(URL))
    start = "2026-09-05"  # the Saturday that starts the 12 weeks
    assert f'href="/admin/activity?person={a.id}&from={start}">Priya Shah</a>' in body
    assert f'href="/admin/activity?kind=risks&from={start}">Risks</a>' in body


def test_the_log_filters_by_kind(client, logged_in_admin, db, user_factory):
    a = user_factory()
    risk = add(db, user_id=a.id, action="risk_updated", entity="risk")
    entry = add(db, user_id=a.id, action="entry_created")
    body = text_of(client.get(LOG + "?kind=risks"))
    assert f'data-entry="{risk.id}"' in body and f'data-entry="{entry.id}"' not in body
    assert '<option value="risks" selected>Risks</option>' in body
    assert "Clear filters" in body
    assert f'data-entry="{entry.id}"' in text_of(client.get(LOG + "?kind=nonsense"))


def test_the_weekly_chart_switches_what_it_counts(client, logged_in_admin, db, user_factory):
    a = user_factory()
    add(db, user_id=a.id, action="login", entity="user")
    body = text_of(client.get(URL + "?metric=signins"))
    assert '<h2 id="h-week">Sign-ins per week</h2>' in body
    assert 'aria-label="This week so far (21 Nov to 26 Nov): 1 sign-in"' in body
    assert 'href="/admin/activity?from=2026-11-21&to=2026-11-26"' in body


def test_retention_shorter_than_the_period_is_noted(client, logged_in_admin, db):
    db.add(AppSetting(key="audit_retention_days", value="30"))
    db.commit()
    assert "Activity keeps entries for 30 days, so figures before Tue 27 Oct 2026 are incomplete." in text_of(
        client.get(URL)
    )


def test_no_trackers_and_no_changes(client, logged_in_admin):
    body = text_of(client.get(URL))
    assert "No trackers to show." in body
    assert "No changes in the last 12 months." in body
    assert "No changes in this period." in body
