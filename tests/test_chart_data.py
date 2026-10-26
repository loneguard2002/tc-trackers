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
