"""The chart data JSON route behind the interactive report charts (database)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(name="Core Rollout", first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 9, 25))


@pytest.fixture
def viewer(client, logged_in_user, grant, small_tracker):
    grant(logged_in_user, small_tracker, "viewer")
    return logged_in_user


def test_chart_data_requires_a_role(client, logged_in_user, small_tracker):
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json").status_code == 404


def test_chart_data_returns_the_tracker_weeks(client, viewer, small_tracker):
    response = client.get(f"/trackers/{small_tracker.id}/report/data.json")
    assert response.status_code == 200
    data = response.get_json()
    assert data["weeks"] == ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]
    assert set(data["series"]) >= {"planned_remaining", "actual_remaining", "forecast_remaining"}
    assert data["unit_label"] == small_tracker.unit_label


def test_chart_data_bad_week(client, viewer, small_tracker):
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json?week=nope").status_code == 400
    assert client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-05").status_code == 404


def test_chart_data_carries_the_report_week_and_the_targets_made_by_then(client, db, viewer, small_tracker):
    from datetime import datetime, timezone

    from report_helpers import add_target_change

    first, second, third = date(2026, 12, 4), date(2026, 12, 18), date(2027, 1, 8)
    add_target_change(db, small_tracker, None, first, datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    add_target_change(db, small_tracker, first, second, datetime(2026, 9, 10, 9, tzinfo=timezone.utc), "Late kit")
    add_target_change(db, small_tracker, second, third, datetime(2026, 9, 24, 9, tzinfo=timezone.utc))
    early = client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-11").get_json()
    assert early["report_week"] == "2026-09-11"
    assert early["targets"] == [
        {"date": "2026-12-04", "number": 1, "current": False},
        {"date": "2026-12-18", "number": 2, "current": True},
    ]
    late = client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-25").get_json()
    assert [t["number"] for t in late["targets"]] == [1, 2, 3]
    assert [t["current"] for t in late["targets"]] == [False, False, True]


def test_chart_data_leaves_out_a_removed_target_but_keeps_its_number(client, db, viewer, small_tracker):
    from datetime import datetime, timezone

    from report_helpers import add_target_change

    add_target_change(db, small_tracker, None, date(2026, 12, 4), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    add_target_change(db, small_tracker, date(2026, 12, 4), None, datetime(2026, 9, 2, 9, tzinfo=timezone.utc))
    data = client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-11").get_json()
    assert data["targets"] == [{"date": "2026-12-04", "number": 1, "current": False}]


def test_chart_data_without_target_history_has_no_targets(client, viewer, small_tracker):
    data = client.get(f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-18").get_json()
    assert data["targets"] == [] and data["report_week"] == "2026-09-18"
    assert {"unit_label", "palette", "weeks", "series", "in_progress"} <= set(data)  # nothing removed
    assert "forecast_end" in data


def test_chart_data_says_whether_to_number_the_targets_and_whether_the_week_is_in_progress(
    client, db, viewer, small_tracker
):
    from datetime import datetime, timezone

    from report_helpers import add_target_change

    url = f"/trackers/{small_tracker.id}/report/data.json?week=2026-09-11"
    add_target_change(db, small_tracker, None, date(2026, 12, 4), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    lone = client.get(url).get_json()
    assert lone["target_numbers"] is False and lone["report_week_in_progress"] is False
    add_target_change(
        db, small_tracker, date(2026, 12, 4), date(2026, 12, 11), datetime(2026, 9, 2, 9, tzinfo=timezone.utc)
    )
    assert client.get(url).get_json()["target_numbers"] is True


def test_chart_payload_numbers_targets_after_a_removal_and_flags_the_week_in_progress():
    from report_helpers import sample_rows

    from tracker.engine.calc import IN_PROGRESS
    from tracker.report.chart_data import chart_payload
    from tracker.trackers.targets import TargetEntry

    removed = [
        TargetEntry(1, date(2026, 12, 4), "set", date(2026, 9, 1), None, "", None, False),
        TargetEntry(2, None, "removed", date(2026, 9, 2), None, "", None, True),
    ]
    rows = sample_rows()
    rows[1] = replace(rows[1], state=IN_PROGRESS)
    payload = chart_payload(SimpleNamespace(unit_label="d"), rows, rows[1].week_ending, removed)
    assert payload["target_numbers"] is True
    assert payload["report_week_in_progress"] is True
    assert chart_payload(SimpleNamespace(unit_label="d"), rows, rows[0].week_ending)["report_week_in_progress"] is False
