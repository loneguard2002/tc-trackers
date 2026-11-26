"""New tracker in five steps: one real form, every step in the page (tracker-new.js shows them a step at a time)."""

from __future__ import annotations

import re

from conftest import post

SETTINGS = {
    "name": "",
    "week_ending_weekday": "4",
    "start_date": "2026-09-04",
    "last_week_ending": "2026-12-25",
    "completed_before_first": "0",
    "moving_average_weeks": "3",
}


def _steps(page: str) -> list[str]:
    return re.findall(r'data-wizard-step="(\d)"', page)


def test_every_step_is_in_the_page_and_the_step_bar_waits_for_the_script(client, logged_in_admin, region_factory):
    region_factory("EMEA", "Europe")
    page = client.get("/trackers/new").get_data(as_text=True)
    assert _steps(page) == ["1", "2", "3", "4", "5"]
    assert 'data-start-step="1"' in page
    assert re.search(r'<ol class="wizard-steps wizard-steps-5" aria-label="Steps" hidden>', page)
    # without the script every field is there and Create tracker submits the form
    for name in (
        "name",
        "unit_label",
        "group_label",
        "description",
        "business_line_id",
        "region_ids",
        "team_id",
        "week_ending_weekday",
        "start_date",
        "last_week_ending",
        "target_completion",
        "completed_before_first",
        "moving_average_weeks",
    ):
        assert f'name="{name}"' in page, name
    assert '<button class="button primary" type="submit" data-wizard-create>Create tracker</button>' in page
    assert "data-wizard-next hidden" in page


def test_a_refused_form_opens_on_the_review_under_the_list_of_corrections(client, logged_in_admin, region_factory):
    region_factory("EMEA", "Europe")
    response = post(client, "/trackers/new", SETTINGS)
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'data-start-step="5"' in page and "A name is required." in page
    assert 'value="2026-12-25"' in page  # what was entered is kept


def test_settings_still_shows_the_three_sections(client, db, tracker_factory, user_factory, grant):
    from conftest import sign_in

    tracker, owner = tracker_factory(name="Core"), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    for section in ("general", "reporting-period", "progress-forecast"):
        assert f'id="{section}"' in page
    assert "data-wizard-step" not in page and "data-step-error" not in page
