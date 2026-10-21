from datetime import date, timedelta

import pytest

from tracker.engine.calc import GroupInput, build_headline, build_week_rows, group_positions
from tracker.engine.weeks import week_endings

FRI = 4
WEEKS = week_endings(date(2026, 9, 4), date(2026, 12, 25))
TARGETS = {w: 50 for w in WEEKS[:8]}
ACTUALS = {date(2026, 9, 4): 40, date(2026, 9, 11): 38, date(2026, 9, 18): 20, date(2026, 9, 25): 40}
REPORT_WEEK = date(2026, 9, 25)


def make_rows(actuals=None, as_of=date(2026, 9, 25), targets=None):
    return build_week_rows(
        WEEKS,
        TARGETS if targets is None else targets,
        ACTUALS if actuals is None else actuals,
        369,
        0,
        3,
        as_of=as_of,
        weekday=FRI,
    )


def make_positions(deployed_total=138):
    groups = [
        GroupInput(1, "Group A", 200, 100, 0, None, None, None, False),
        GroupInput(2, "Group B", 169, 0, 0, None, None, None, False),
    ]
    return group_positions(groups, {1: deployed_total - 100})


@pytest.fixture
def rows():
    return make_rows()


@pytest.fixture
def headline(rows):
    return build_headline(rows, make_positions(), 0, date(2026, 10, 30), REPORT_WEEK)


def test_cumulative_and_remaining(rows):
    r = rows[3]
    assert (r.cum_actual, r.actual_remaining, r.cum_target, r.planned_remaining) == (138, 231, 200, 169)
    assert r.variance == -10
    assert r.pct_complete == pytest.approx(138 / 369)


def test_moving_average_short_start(rows):
    assert rows[0].moving_average == 40 and rows[1].moving_average == 39
    assert rows[3].moving_average == pytest.approx(32.667, abs=1e-3)


def test_states_and_future_rows(rows):
    assert [r.state for r in rows[:4]] == ["complete"] * 4
    assert rows[4].state == "future"
    assert rows[4].actual is None and rows[4].cum_actual is None and rows[4].pct_complete is None
    assert rows[4].moving_average is None
    assert rows[4].forecast_remaining == pytest.approx(231 - 98 / 3)
    assert rows[3].forecast_remaining == 231


def test_cum_target_none_after_first_missing_target(rows):
    assert rows[7].cum_target == 400 and rows[7].planned_remaining == -31
    assert rows[8].cum_target is None and rows[8].planned_remaining is None


def test_forecast_remaining_floors_at_zero(rows):
    assert rows[-1].forecast_remaining == 0


def test_forecast_completion(headline):
    assert headline.forecast_based_on == date(2026, 9, 25)
    assert headline.forecast_completion == date(2026, 9, 25) + timedelta(weeks=8)  # ceil(231/32.667)=8


def test_planned_completion(headline):  # 8 x 50 = 400 >= 369
    assert headline.planned_completion == date(2026, 10, 23)


def test_empty_week_counts_as_zero():
    rows = make_rows(actuals={date(2026, 9, 4): 40, date(2026, 9, 25): 30})
    assert rows[1].state == "complete" and rows[1].actual == 0
    assert rows[2].actual == 0
    assert rows[2].moving_average == pytest.approx(13.333, abs=1e-3)
    assert rows[3].moving_average == pytest.approx(10)
    assert rows[3].cum_actual == 70


def test_in_progress_week_excluded_from_average():
    rows = make_rows(as_of=date(2026, 9, 30))  # 2 Oct in progress
    assert rows[4].state == "in_progress" and rows[4].moving_average is None
    assert rows[3].moving_average == pytest.approx(32.667, abs=1e-3)
    assert rows[4].actual == 0 and rows[4].cum_actual == 138
    assert rows[5].state == "future"
    assert rows[4].forecast_remaining == pytest.approx(231 - 98 / 3)


def test_in_progress_week_shows_actual_but_not_forecast_basis():
    actuals = {**ACTUALS, date(2026, 10, 2): 10}
    rows = make_rows(actuals=actuals, as_of=date(2026, 9, 30))
    assert rows[4].actual == 10 and rows[4].cum_actual == 148 and rows[4].actual_remaining == 221
    h = build_headline(rows, make_positions(), 0, date(2026, 10, 30), date(2026, 10, 2))
    assert h.forecast_based_on == date(2026, 9, 25)


def test_verdict_behind(headline):  # forecast 20 Nov, target 30 Oct -> 21 days
    assert headline.forecast_vs_target_days == 21
    assert headline.verdict == "Forecast 3 weeks behind target"


def test_verdict_singular_behind(rows):
    h = build_headline(rows, make_positions(), 0, date(2026, 11, 13), REPORT_WEEK)
    assert h.verdict == "Forecast 1 week behind target"


def test_verdict_ahead_and_on_track(rows):
    h = build_headline(rows, make_positions(), 0, date(2026, 12, 4), REPORT_WEEK)  # forecast 20 Nov, 14 days early
    assert h.verdict == "Forecast 2 weeks ahead of target"
    h = build_headline(rows, make_positions(), 0, date(2026, 11, 27), REPORT_WEEK)  # 7 days early
    assert h.verdict == "Forecast 1 week ahead of target"
    h = build_headline(rows, make_positions(), 0, date(2026, 11, 20), REPORT_WEEK)
    assert h.verdict == "On track for target"


def test_verdict_no_target_set(rows):
    h = build_headline(rows, make_positions(), 0, None, REPORT_WEEK)
    assert h.verdict == "No target set"
    assert h.weeks_left is None and h.required_rate is None and h.forecast_vs_target_days is None


def test_verdict_complete():
    actuals = {w: 100 for w in WEEKS[:4]}
    rows = build_week_rows(WEEKS, TARGETS, actuals, 369, 0, 3, as_of=date(2026, 9, 25), weekday=FRI)
    positions = group_positions([GroupInput(1, "Group A", 369, 0, 0, None, None, None, False)], {1: 369})
    h = build_headline(rows, positions, 0, date(2026, 10, 30), REPORT_WEEK)
    assert h.remaining == 0 and h.verdict == "Complete"


def test_weeks_left_and_required_rate(headline):
    assert headline.weeks_left == 5
    assert headline.required_rate == pytest.approx(231 / 5)
    assert headline.remaining == 231 and headline.total_scope == 369 and headline.completed == 138
    assert headline.pct_complete == pytest.approx(138 / 369)
    assert headline.forecast_rate == pytest.approx(32.667, abs=1e-3)


def test_weeks_left_zero_when_target_passed(rows):
    h = build_headline(rows, make_positions(), 0, date(2026, 9, 11), REPORT_WEEK)
    assert h.weeks_left == 0 and h.required_rate is None


def test_this_and_next_week_figures(headline):
    assert headline.this_week_actual == 40 and headline.this_week_target == 50
    assert headline.next_week_target == 50


def test_zero_rate_gives_no_forecast():
    rows = make_rows(actuals={})
    h = build_headline(rows, make_positions(0), 0, date(2026, 10, 30), REPORT_WEEK)
    assert h.forecast_completion is None and h.verdict == "No forecast yet"


def test_headline_no_targets_no_actuals():
    rows = build_week_rows(WEEKS, {}, {}, 0, 0, 3, as_of=date(2026, 9, 1), weekday=FRI)
    h = build_headline(rows, [], 0, None, date(2026, 9, 4))
    assert h.forecast_completion is None and h.planned_completion is None and h.verdict == "No forecast yet"
    assert h.pct_complete is None


def test_group_positions_deployed_includes_starting():
    groups = [GroupInput(7, "Group A", 200, 135, 3, None, "Green", "ok", False)]
    (p,) = group_positions(groups, {7: 5})
    assert p.deployed == 140 and p.remaining == 60 and p.ready_not_complete == 3
    assert p.pct_complete == pytest.approx(0.7) and p.rag == "Green" and p.comment == "ok"


def test_group_positions_no_entries_and_zero_baseline():
    groups = [
        GroupInput(1, "A", 0, 0, 0, None, None, None, True),
        GroupInput(2, "B", 10, 4, 0, None, None, None, False),
    ]
    a, b = group_positions(groups, {})
    assert a.pct_complete is None and a.retired is True
    assert b.deployed == 4 and b.remaining == 6


def test_retired_group_counts_in_headline(rows):
    groups = [
        GroupInput(1, "A", 300, 100, 0, None, None, None, False),
        GroupInput(2, "B", 69, 38, 0, None, None, None, True),
    ]
    h = build_headline(rows, group_positions(groups, {}), 0, None, REPORT_WEEK)
    assert h.total_scope == 369 and h.completed == 138 and h.totals_check_ok


def test_totals_check_flags_mismatch(rows):
    h = build_headline(rows, make_positions(deployed_total=140), 0, None, REPORT_WEEK)
    assert h.totals_check_ok is False
    h = build_headline([], [], 0, None, REPORT_WEEK)
    assert h.totals_check_ok is True
