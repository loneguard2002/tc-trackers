"""The engine reproduces the workbook's own figures (spec section 9).

Runs only when ``tests/fixtures/tc_win11_golden.json`` exists. Create it with ``tools/capture_workbook_golden.py``
from a copy of the workbook that has been opened and saved in Excel. Figures must match exactly; dates are earlier
than the workbook's by 3 days (a Monday report date becomes the Friday week-ending).
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from tracker.engine.calc import GroupInput, build_headline, build_week_rows, group_positions
from tracker.engine.weeks import report_date_to_week_ending

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "tc_win11_golden.json"
WEEKDAY = 4  # Friday
SHIFT = timedelta(days=3)

pytestmark = pytest.mark.skipif(not GOLDEN.exists(), reason="golden workbook capture not provided")


def _d(text):
    return None if text is None else date.fromisoformat(text)


def _same(actual, expected):
    if expected is None or actual is None:
        assert actual is None and expected is None
    elif isinstance(expected, float) or isinstance(actual, float):
        assert actual == pytest.approx(expected, abs=1e-9)
    else:
        assert actual == expected


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def computed(golden):
    s, expected = golden["settings"], golden["expected"]
    ending = {w["report_date"]: report_date_to_week_ending(_d(w["report_date"]), WEEKDAY) for w in golden["weeks"]}
    weeks = [ending[w["report_date"]] for w in golden["weeks"]]
    targets = {ending[w["report_date"]]: w["target"] for w in golden["weeks"]}
    actuals = {ending[w["report_date"]]: w["actual"] for w in golden["weeks"] if w["actual"] is not None}
    basis = _d(expected["forecast_based_on"])
    as_of = basis - SHIFT if basis else weeks[0] - timedelta(days=7)
    total_scope = sum(g["baseline"] for g in golden["groups"])
    rows = build_week_rows(
        weeks, targets, actuals, total_scope, s["completed_before_first"], s["moving_average_weeks"], as_of, WEEKDAY
    )
    groups = [
        GroupInput(i, g["name"], g["baseline"], g["starting_completed"], g["ready_not_complete"], None, None, "", False)
        for i, g in enumerate(golden["groups"])
    ]
    headline = build_headline(
        rows, group_positions(groups, {}), s["completed_before_first"], _d(s["target_completion"]), as_of
    )
    return rows, headline


def test_every_weekly_figure_matches(golden, computed):
    rows, _ = computed
    assert len(rows) == len(golden["weeks"])
    for row, week in zip(rows, golden["weeks"], strict=True):
        assert row.week_ending == _d(week["report_date"]) - SHIFT
        for key, expected in week["expected"].items():
            _same(getattr(row, key), expected)


def test_forecast_figures_match_with_dates_shifted(golden, computed):
    rows, headline = computed
    expected = golden["expected"]
    for key, actual in [
        ("forecast_based_on", headline.forecast_based_on),
        ("planned_completion", headline.planned_completion),
        ("forecast_completion", headline.forecast_completion),
    ]:
        want = _d(expected[key])
        assert actual == (want - SHIFT if want else None), key
    _same(headline.forecast_rate, expected["forecast_rate"])
    basis = {r.week_ending: r for r in rows}.get(headline.forecast_based_on)
    _same(basis.actual_remaining if basis else None, expected["remaining_at_basis"])
