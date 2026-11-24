"""The chart data JSON route behind the interactive report charts (database)."""

from __future__ import annotations

from datetime import date

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
