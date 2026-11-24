"""The report's location pop-up: editors set a location's status from the new view."""

from __future__ import annotations

import json
import re
from datetime import date
from html import unescape

import pytest
from conftest import post
from sqlalchemy import select
from test_report import WEEKS, seed

from tracker.models import AuditLog, Group


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1], target_completion=date(2026, 12, 25))


def report_page(client, tracker, week=WEEKS[1]):
    return client.get(f"/trackers/{tracker.id}/report?view=new&week={week.isoformat()}").get_data(as_text=True)


def status_url(tracker, group):
    return f"/trackers/{tracker.id}/groups/{group.id}/status"


def test_an_editor_gets_the_chip_as_a_link_and_the_pop_up(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    group = seed(db, small_tracker)
    group.rag, group.comment, group.ready_not_complete = None, "Late kit", 4
    group.planned_completion = date(2026, 10, 30)
    db.commit()
    html = report_page(client, small_tracker)
    link = re.search(
        r"<a class=\"glance-chip glance-chip-none glance-chip-button\" href=\"([^\"]+)\" data-location-edit='([^']+)'",
        html,
    )
    assert link, "the chip is a link for an editor"
    assert link.group(1) == f"/trackers/{small_tracker.id}/groups/{group.id}"  # the full edit page without JavaScript
    data = json.loads(unescape(link.group(2)))
    assert data == {
        "action": status_url(small_tracker, group),
        "name": "Site A",
        "rag": "",
        "planned_completion": "2026-10-30",
        "ready_not_complete": 4,
        "comment": "Late kit",
    }
    assert '<dialog id="location-dialog"' in html and 'name="week" value="2026-09-11"' in html
    assert "report-locations.js" in html


def test_a_viewer_sees_the_status_only(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "viewer")
    seed(db, small_tracker)
    html = report_page(client, small_tracker)
    assert "data-location-edit" not in html and 'id="location-dialog"' not in html
    assert '<span class="glance-chip glance-chip-none">' in html


def test_an_archived_tracker_offers_no_pop_up(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    seed(db, small_tracker)
    small_tracker.status = "archived"
    db.commit()
    assert "data-location-edit" not in report_page(client, small_tracker)


def test_an_editor_saves_the_status_and_returns_to_the_report_week(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    group = seed(db, small_tracker)
    response = post(
        client,
        status_url(small_tracker, group),
        data={
            "week": "2026-09-11",
            "rag": "Amber",
            "planned_completion": "2026-11-06",
            "ready_not_complete": "3",
            "comment": "Waiting for power",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/trackers/{small_tracker.id}/report?week=2026-09-11")
    db.refresh(group)
    assert (group.rag, group.planned_completion, group.ready_not_complete, group.comment) == (
        "Amber",
        date(2026, 11, 6),
        3,
        "Waiting for power",
    )
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "group_updated")).one()
    assert audit.detail["rag"] == [None, "Amber"] and audit.entity_id == str(group.id)
    html = client.get(response.headers["Location"] + "&view=new").get_data(as_text=True)
    assert "Site A saved." in html and "glance-chip-amber" in html


def test_the_pop_up_never_changes_the_name_baseline_or_starting_figure(
    client, db, small_tracker, logged_in_user, grant
):
    grant(logged_in_user, small_tracker, "owner")
    group = seed(db, small_tracker)
    post(
        client,
        status_url(small_tracker, group),
        data={"week": "2026-09-11", "rag": "Green", "name": "Renamed", "baseline": "5", "starting_completed": "9"},
    )
    db.refresh(group)
    assert (group.rag, group.name, group.baseline, group.starting_completed) == ("Green", "Site A", 100, 0)


def test_a_bad_status_is_refused_and_nothing_changes(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    group = seed(db, small_tracker)
    response = post(client, status_url(small_tracker, group), data={"week": "2026-09-11", "rag": "Purple"})
    assert response.status_code == 302
    db.refresh(group)
    assert group.rag is None
    html = client.get(response.headers["Location"] + "&view=new").get_data(as_text=True)
    assert "The status must be Green, Amber or Red." in html
    assert not db.scalars(select(AuditLog).where(AuditLog.action == "group_updated")).first()


def test_a_week_that_is_not_a_date_returns_to_the_current_report(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    group = seed(db, small_tracker)
    response = post(client, status_url(small_tracker, group), data={"week": "javascript:x", "rag": "Green"})
    assert response.headers["Location"].endswith(f"/trackers/{small_tracker.id}/report")


def test_viewers_and_other_trackers_cannot_set_a_status(
    client, db, small_tracker, tracker_factory, logged_in_user, grant
):
    grant(logged_in_user, small_tracker, "viewer")
    group = seed(db, small_tracker)
    assert post(client, status_url(small_tracker, group), data={"rag": "Red"}).status_code in (403, 404)
    other = tracker_factory(first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    grant(logged_in_user, other, "editor")
    assert post(client, status_url(other, group), data={"rag": "Red"}).status_code == 404
    db.refresh(group)
    assert group.rag is None


def test_an_archived_tracker_refuses_a_status(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    group = seed(db, small_tracker)
    small_tracker.status = "archived"
    db.commit()
    post(client, status_url(small_tracker, group), data={"week": "2026-09-11", "rag": "Red"})
    db.refresh(group)
    assert group.rag is None


def test_group_ids_in_another_tracker_are_not_found(client, db, small_tracker, logged_in_user, grant):
    grant(logged_in_user, small_tracker, "editor")
    seed(db, small_tracker)
    missing = Group(id=999999, tracker_id=small_tracker.id, name="x", baseline=1)
    assert post(client, status_url(small_tracker, missing), data={"rag": "Red"}).status_code == 404
