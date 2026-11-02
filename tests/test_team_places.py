"""Teams have a region and a location: the two drop-downs, their checks, the Activity details and where they show."""

import html
import re

from sqlalchemy import func, select

from tests.conftest import post
from tracker.activity.labels import action_label
from tracker.lists.catalogue import LOCATION_CHOICE_ERROR, LOCATION_REGION_MISMATCH, LOCATION_REQUIRED
from tracker.models import AuditLog, Team


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def place_of(region, location) -> dict[str, str]:
    return {"region_id": str(region.id), "location_id": str(location.id)}


def select_html(page: str, select_id: str) -> str:
    return re.search(rf'<select id="{select_id}".*?</select>', page, re.S).group(0)


def selected_value(page: str, select_id: str) -> str | None:
    match = re.search(r'<option value="(\d*)"[^>]*\sselected', select_html(page, select_id))
    return match.group(1) if match else None


def tree_item(page: str, name: str) -> str:
    tree = re.search(r'<ul class="team-tree">.*', page, re.S).group(0)
    start = tree.index(f">{name}<")
    return tree[start : tree.index("</li>", start)]


def test_a_new_team_needs_a_region_and_a_location(client, logged_in_admin, db, region_factory, location_factory):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    page = post(client, "/admin/teams", {"name": "Desktop"})
    assert page.status_code == 400 and LOCATION_REQUIRED in text_of(page)
    for partial in ({"region_id": str(emea.id)}, {"location_id": str(geneva.id)}):
        page = post(client, "/admin/teams", {"name": "Desktop", **partial})
        assert page.status_code == 400 and LOCATION_REQUIRED in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0
    assert post(client, "/admin/teams", {"name": "Desktop", **place_of(emea, geneva)}).status_code == 302
    team = db.scalars(select(Team)).one()
    assert team.location_id == geneva.id
    [entry] = entries(db, "team_created")
    assert entry.detail == {"name": "Desktop", "parent": None, "location": "Geneva, Switzerland (EMEA)"}


def test_a_place_error_joins_the_other_errors_and_the_choice_is_kept(
    client, logged_in_admin, db, region_factory, location_factory
):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    page = post(client, "/admin/teams", {"name": "   "})
    body = text_of(page)
    assert page.status_code == 400 and "Enter a team name." in body and LOCATION_REQUIRED in body
    page = post(client, "/admin/teams", {"name": "   ", **place_of(emea, geneva)})
    raw = page.get_data(as_text=True)
    assert page.status_code == 400 and LOCATION_REQUIRED not in text_of(page)
    assert selected_value(raw, "region_id") == str(emea.id)
    assert selected_value(raw, "location_id") == str(geneva.id)


def test_a_location_from_another_region_is_refused(client, logged_in_admin, db, region_factory, location_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    geneva = location_factory(emea)
    singapore = location_factory(apac, city="Singapore", country="Singapore")
    page = post(client, "/admin/teams", {"name": "Desktop", **place_of(apac, geneva)})
    assert page.status_code == 400 and LOCATION_REGION_MISMATCH in text_of(page)
    assert db.scalar(select(func.count()).select_from(Team)) == 0 and entries(db, "team_created") == []
    created = post(client, "/admin/teams", {"name": "Desktop", **place_of(apac, singapore)})
    assert created.status_code == 302
    team = db.scalars(select(Team)).one()
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktop 2", **place_of(apac, geneva)})
    assert page.status_code == 400 and LOCATION_REGION_MISMATCH in text_of(page)
    db.expire_all()
    team = db.get(Team, team.id)
    assert team.name == "Desktop" and team.location_id == singapore.id
    assert entries(db, "team_renamed") == []


def test_an_unknown_or_retired_location_is_refused_for_a_new_choice(
    client, logged_in_admin, db, region_factory, location_factory
):
    emea, old_region = region_factory("EMEA"), region_factory("OLD", retired=True)
    retired = location_factory(emea, city="Basel", retired=True)
    in_retired_region = location_factory(old_region, city="Bern")
    for region, location_id in (
        (emea, "99999"),
        (emea, "abc"),
        (emea, str(retired.id)),
        (old_region, str(in_retired_region.id)),
    ):
        page = post(
            client, "/admin/teams", {"name": "Desktop", "region_id": str(region.id), "location_id": location_id}
        )
        assert page.status_code == 400 and LOCATION_CHOICE_ERROR in text_of(page), location_id
    assert db.scalar(select(func.count()).select_from(Team)) == 0


def test_an_existing_team_shows_region_not_set_and_its_next_save_needs_a_place(
    client, logged_in_admin, db, team_factory, region_factory, location_factory
):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    team = team_factory("Desktop")
    index = client.get("/admin/teams").get_data(as_text=True)
    assert '<span class="team-place is-unset">Region not set</span>' in tree_item(index, "Desktop")
    page = client.get(f"/admin/teams/{team.id}").get_data(as_text=True)
    assert "Region not set" in page
    assert selected_value(page, "region_id") == "" and selected_value(page, "location_id") == ""
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktop", "description": ""})
    assert page.status_code == 400 and LOCATION_REQUIRED in text_of(page)
    [tag] = re.findall(r"<details\b[^>]*>", page.get_data(as_text=True))
    assert re.search(r"\sopen\b", tag)
    response = post(
        client, f"/admin/teams/{team.id}/rename", {"name": "Desktop", "description": "", **place_of(emea, geneva)}
    )
    assert response.status_code == 302
    db.expire_all()
    assert db.get(Team, team.id).location_id == geneva.id


def test_saving_a_team_at_a_retired_location_keeps_it(
    client, logged_in_admin, db, team_factory, region_factory, location_factory
):
    emea = region_factory("EMEA")
    old = location_factory(emea, retired=True)
    team = team_factory("Desktop", location_id=old.id)
    page = text_of(client.get(f"/admin/teams/{team.id}"))
    assert "Geneva, Switzerland (retired)" in page
    assert selected_value(page, "location_id") == str(old.id)
    assert selected_value(page, "region_id") == str(emea.id)
    assert "Geneva, Switzerland" not in select_html(text_of(client.get("/admin/teams")), "location_id")
    response = post(
        client, f"/admin/teams/{team.id}/rename", {"name": "Desktop 2", "description": "", **place_of(emea, old)}
    )
    assert response.status_code == 302
    db.expire_all()
    assert db.get(Team, team.id).location_id == old.id and db.get(Team, team.id).name == "Desktop 2"


def test_saving_a_team_in_a_retired_region_keeps_it(
    client, logged_in_admin, db, team_factory, region_factory, location_factory
):
    old = region_factory("OLD", name="Old region", retired=True)
    bern = location_factory(old, city="Bern")
    team = team_factory("Desktop", location_id=bern.id)
    page = text_of(client.get(f"/admin/teams/{team.id}"))
    assert re.search(r">OLD – Old region \(retired\)</option>", select_html(page, "region_id"))
    assert '<optgroup label="OLD – Old region (retired)"' in select_html(page, "location_id")
    assert "Bern, Switzerland (retired)" in page
    response = post(
        client, f"/admin/teams/{team.id}/rename", {"name": "Desktop", "description": "Kept", **place_of(old, bern)}
    )
    assert response.status_code == 302
    db.expire_all()
    assert db.get(Team, team.id).location_id == bern.id
    assert "OLD" not in select_html(text_of(client.get("/admin/teams")), "region_id")


def test_the_place_fields_group_locations_by_region(client, logged_in_admin, region_factory, location_factory):
    emea = region_factory("EMEA", name="Europe, Middle East and Africa")
    apac = region_factory("APAC", name="Asia Pacific")
    region_factory("LATAM")  # no locations: not offered
    location_factory(emea, city="Zurich")
    location_factory(emea, city="Geneva")
    location_factory(apac, city="Singapore", country="Singapore")
    page = text_of(client.get("/admin/teams"))
    regions = select_html(page, "region_id")
    assert re.search(r"<select [^>]*\brequired\b", regions) and "data-region-select" in regions
    assert re.findall(r"<option[^>]*>([^<]*)</option>", regions) == [
        "Choose a region",
        "APAC – Asia Pacific",
        "EMEA – Europe, Middle East and Africa",
    ]
    assert "LATAM" not in regions
    locations = select_html(page, "location_id")
    assert re.search(r"<select [^>]*\brequired\b", locations) and "data-location-select" in locations
    assert re.search(r'<option value=""[^>]*>Choose a location</option>', locations)
    groups = re.findall(r'<optgroup label="([^"]*)" data-region="(\d+)">(.*?)</optgroup>', locations, re.S)
    assert [(label, int(region)) for label, region, _ in groups] == [
        ("APAC – Asia Pacific", apac.id),
        ("EMEA – Europe, Middle East and Africa", emea.id),
    ]
    assert re.findall(r">([^<]+)</option>", groups[1][2]) == ["Geneva, Switzerland", "Zurich, Switzerland"]


def test_tree_and_team_page_show_the_place(client, logged_in_admin, team_factory, region_factory, location_factory):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    infra = team_factory("Infrastructure", location_id=geneva.id)
    team_factory("Windows", parent=infra)
    for url in ("/admin/teams", f"/admin/teams/{infra.id}"):
        page = text_of(client.get(url))
        assert '<span class="team-place">EMEA · Geneva</span>' in tree_item(page, "Infrastructure")
        assert '<span class="team-place is-unset">Region not set</span>' in tree_item(page, "Windows")
    page = text_of(client.get(f"/admin/teams/{infra.id}"))
    header = re.search(r'<header class="team-header.*?</header>', page, re.S).group(0)
    assert "EMEA · Geneva, Switzerland" in header
    assert selected_value(page, "region_id") == str(emea.id)
    assert selected_value(page, "location_id") == str(geneva.id)


def test_location_change_is_logged_as_a_details_change(
    client, logged_in_admin, db, team_factory, region_factory, location_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    geneva = location_factory(emea)
    singapore = location_factory(apac, city="Singapore", country="Singapore")
    team = team_factory("Desktop")
    assert (
        post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktop", **place_of(emea, geneva)}).status_code == 302
    )
    assert (
        post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktops", **place_of(apac, singapore)}).status_code
        == 302
    )
    first, second = entries(db, "team_renamed")
    assert first.detail == {
        "team": "Desktop",
        "before": {"location": None},
        "after": {"location": "Geneva, Switzerland (EMEA)"},
    }
    assert second.detail == {
        "team": "Desktop",
        "before": {"name": "Desktop", "location": "Geneva, Switzerland (EMEA)"},
        "after": {"name": "Desktops", "location": "Singapore, Singapore (APAC)"},
    }
    assert (
        post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktops", **place_of(apac, singapore)}).status_code
        == 302
    )
    assert len(entries(db, "team_renamed")) == 2
    assert action_label("team_renamed") == "Team details changed"
