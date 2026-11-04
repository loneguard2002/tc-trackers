"""Administration screens for regions, locations and business lines (database required)."""

import html
import json
import re

import pytest
from sqlalchemy import select

from tests.conftest import post
from tracker.audit import NO_CHANGES_MESSAGE
from tracker.lists.catalogue import team_places
from tracker.lists.countries import COUNTRY_CHOICE_ERROR, COUNTRY_REQUIRED
from tracker.lists.views import (
    LOCATION_CODE_FORMAT,
    LOCATION_CODE_REQUIRED,
    LOCATION_CODE_TAKEN,
    LOCATION_TAKEN,
    REGION_CODE_REQUIRED,
    REGION_CODE_TAKEN,
)
from tracker.models import AuditLog, BusinessLine, Location, Region, TrackerRegion


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query))


def fresh(db, model, entry_id):
    db.expire_all()
    return db.scalar(select(model).where(model.id == entry_id))


def row_of(page: str, row_id: str) -> str:
    """The markup of the table row with this id."""
    start = page.index(f'<tr id="{row_id}"')
    return page[start : page.index("</tr>", start)]


def cells_of(row: str) -> list[str]:
    """The text a sighted reader sees in each cell of a row (screen-reader-only text left out)."""
    row = re.sub(r'<span class="sr-only">.*?</span>', "", row)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in cells]


def dialog_of(page: str, name: str) -> tuple[str, str]:
    """The opening tag and the whole markup of the add or edit dialog."""
    start = page.index(f'<dialog id="{name}-dialog"')
    return page[start : page.index(">", start) + 1], page[start : page.index("</dialog>", start)]


def is_open(tag: str) -> bool:
    return re.search(r"\sopen[\s>]", tag) is not None


# --- Access ---------------------------------------------------------------------------------------------------------


def test_lists_are_for_administrators_only(client, logged_in_user, give_set, db, region_factory, location_factory):
    give_set(["manage_teams", "manage_users"], user=logged_in_user)
    region = region_factory("APAC")
    location = location_factory(region)
    for url in ("/admin/regions", "/admin/regions/new", f"/admin/regions/{region.id}/edit", "/admin/business-lines"):
        assert client.get(url).status_code == 403
    assert post(client, "/admin/regions", {"code": "EMEA", "name": "Europe"}).status_code == 403
    for url, data in (
        (f"/admin/regions/{region.id}", {"action": "delete"}),
        (f"/admin/regions/{region.id}/locations", {"code": "TYO", "city": "Tokyo", "country_code": "JP"}),
        (f"/admin/locations/{location.id}", {"action": "retire"}),
        ("/admin/business-lines", {"name": "Brokerage"}),
    ):
        assert post(client, url, data).status_code == 403
    assert db.scalar(select(Region.code).where(Region.id == region.id)) == "APAC"
    assert entries(db) == []


def test_lists_send_signed_out_visitors_to_sign_in(client):
    for url in ("/admin/regions", "/admin/regions/new", "/admin/regions/1/edit"):
        response = client.get(url)
        assert response.status_code == 302 and "/login" in response.headers["Location"]


# --- Regions and locations ------------------------------------------------------------------------------------------


def test_admin_adds_a_region_and_a_location_and_both_are_logged(client, logged_in_admin, db):
    response = post(client, "/admin/regions", {"code": " EMEA ", "name": "Europe, Middle East and Africa"})
    assert response.status_code == 302
    region = db.scalars(select(Region)).one()
    assert response.headers["Location"].endswith(f"/admin/regions#region-{region.id}")
    assert (region.code, region.name, region.retired) == ("EMEA", "Europe, Middle East and Africa", False)
    response = post(
        client, f"/admin/regions/{region.id}/locations", {"code": " gva ", "city": " Geneva ", "country_code": "ch"}
    )
    assert response.status_code == 302
    location = db.scalars(select(Location)).one()
    assert (location.region_id, location.code, location.city, location.country_code) == (
        region.id,
        "GVA",
        "Geneva",
        "CH",
    )
    logged = entries(db)
    assert [e.action for e in logged] == ["region_created", "location_created"]
    assert [e.entity for e in logged] == ["region", "location"]
    assert [e.entity_id for e in logged] == [str(region.id), str(location.id)]
    assert all(e.tracker_id is None and e.user_id == logged_in_admin.id for e in logged)
    assert logged[0].detail == {"region": "EMEA"}
    assert logged[1].detail == {"location": "Geneva, Switzerland", "code": "GVA", "region": "EMEA"}
    page = text_of(client.get("/admin/regions"))
    assert "<h1>Regions</h1>" in page
    assert "Regions group locations, and trackers say which regions they cover." in page
    assert "Europe, Middle East and Africa" in page
    assert "<title>Regions · Progress Tracker</title>" in page


def test_regions_are_listed_by_code_ignoring_case(client, logged_in_admin, region_factory):
    emea, apac, latam = region_factory("emea"), region_factory("APAC"), region_factory("Latam")
    page = text_of(client.get("/admin/regions"))
    assert page.index(f'id="region-{apac.id}"') < page.index(f'id="region-{emea.id}"')
    assert page.index(f'id="region-{emea.id}"') < page.index(f'id="region-{latam.id}"')


def test_region_fields_are_required_and_limited(client, logged_in_admin, db):
    response = post(client, "/admin/regions", {"code": " ", "name": ""})
    assert response.status_code == 400
    page = text_of(response)
    assert "Please correct the following:" in page
    assert "Enter a region short name." in page and "Enter a region name." in page
    response = post(client, "/admin/regions", {"code": "x" * 21, "name": "y" * 101})
    assert response.status_code == 400
    page = text_of(response)
    assert "A region short name can be at most 20 characters." in page
    assert "A region name can be at most 100 characters." in page
    assert post(client, "/admin/regions", {"code": "x" * 20, "name": "y" * 100}).status_code == 302
    assert len(entries(db, "region_created")) == 1


def test_location_fields_are_required_and_limited(client, logged_in_admin, db, region_factory):
    region = region_factory()
    response = post(client, f"/admin/regions/{region.id}/locations", {"code": "", "city": "", "country_code": " "})
    assert response.status_code == 400
    page = text_of(response)
    assert "Enter a location code." in page and "Enter a city." in page and "Choose a country." in page
    response = post(
        client, f"/admin/regions/{region.id}/locations", {"code": "LON", "city": "x" * 101, "country_code": "GB"}
    )
    assert response.status_code == 400
    page = text_of(response)
    assert "A city can be at most 100 characters." in page
    assert db.scalars(select(Location)).all() == []
    assert (
        post(
            client, "/admin/regions/999999/locations", {"code": "TYO", "city": "Tokyo", "country_code": "JP"}
        ).status_code
        == 404
    )


def test_duplicate_names_are_refused_ignoring_case(
    client, logged_in_admin, db, region_factory, location_factory, business_line_factory
):
    emea = region_factory("EMEA", "Europe, Middle East and Africa")
    apac = region_factory("APAC")
    location_factory(emea, "Geneva", "CH")
    business_line_factory("Tradition brokerage")
    response = post(client, "/admin/regions", {"code": "emea", "name": "europe, middle east and africa"})
    assert response.status_code == 400
    page = text_of(response)
    assert "A region with that short name already exists." in page
    assert "A region with that name already exists." in page
    response = post(
        client, f"/admin/regions/{apac.id}/locations", {"code": "GVA", "city": "geneva", "country_code": "CH"}
    )
    assert response.status_code == 400
    assert "A location with that city and country already exists." in text_of(response)
    response = post(client, "/admin/business-lines", {"name": "TRADITION BROKERAGE"})
    assert response.status_code == 400
    assert "A business line with that name already exists." in text_of(response)
    # Saving another entry under a taken name is refused in the same words.
    response = post(client, f"/admin/regions/{apac.id}", {"action": "save", "code": "Emea", "name": "Asia Pacific"})
    assert response.status_code == 400
    assert "A region with that short name already exists." in text_of(response)
    assert db.scalar(select(Region.code).where(Region.id == apac.id)) == "APAC"
    assert len(db.scalars(select(Location)).all()) == 1
    assert entries(db) == []
    # An entry keeps its own name with a change of case.
    response = post(client, f"/admin/regions/{emea.id}", {"action": "save", "code": "Emea", "name": emea.name})
    assert response.status_code == 302
    assert fresh(db, Region, emea.id).code == "Emea"


def test_a_concurrent_duplicate_gives_the_same_message(client, logged_in_admin, db, monkeypatch, region_factory):
    region_factory("EMEA", "Europe")
    from tracker.lists import views

    monkeypatch.setattr(views, "_region_errors", lambda *args, **kwargs: [])  # the check passes; the index refuses
    response = post(client, "/admin/regions", {"code": "emea", "name": "Elsewhere"})
    assert response.status_code == 400
    assert "A region with that short name already exists." in text_of(response)
    assert len(db.scalars(select(Region)).all()) == 1


def test_saving_a_region_logs_the_changed_fields_only(client, logged_in_admin, db, region_factory):
    region = region_factory("EMEA", "Europe")
    response = post(
        client, f"/admin/regions/{region.id}", {"action": "save", "code": "EMEA", "name": "Europe and Africa"}
    )
    assert response.status_code == 302
    assert fresh(db, Region, region.id).name == "Europe and Africa"
    entry = entries(db, "region_changed")[0]
    assert (entry.entity, entry.entity_id, entry.tracker_id) == ("region", str(region.id), None)
    assert entry.detail == {"region": "EMEA", "before": {"name": "Europe"}, "after": {"name": "Europe and Africa"}}


def test_moving_a_location_moves_its_teams_and_logs_the_count(
    client, logged_in_admin, db, region_factory, location_factory, team_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    place = location_factory(emea)
    team_factory("A", location_id=place.id)
    team_factory("B", location_id=place.id)
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "code": place.code, "city": "Geneva", "country_code": "CH", "region_id": str(apac.id)},
    )
    assert response.status_code == 302
    db.expire_all()
    assert {p.region_code for p in team_places(db).values()} == {"APAC"}
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "location_changed")).one()
    assert entry.detail["teams"] == 2
    assert entry.detail["before"] == {"region": "EMEA"} and entry.detail["after"] == {"region": "APAC"}
    assert entry.detail["location"] == "Geneva, Switzerland"


def test_renaming_a_location_logs_without_a_team_count(
    client, logged_in_admin, db, region_factory, location_factory, team_factory
):
    region = region_factory()
    place = location_factory(region)
    team_factory("A", location_id=place.id)
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "code": place.code, "city": "Genève", "country_code": "CH", "region_id": str(region.id)},
    )
    assert response.status_code == 302
    entry = entries(db, "location_changed")[0]
    assert entry.detail == {
        "location": "Geneva, Switzerland",
        "before": {"city": "Geneva"},
        "after": {"city": "Genève"},
    }


def test_a_location_cannot_move_to_a_retired_or_unknown_region(
    client, logged_in_admin, db, region_factory, location_factory
):
    emea, old = region_factory("EMEA"), region_factory("OLD", retired=True)
    place = location_factory(emea)
    for region_id in (str(old.id), "999999", "x", ""):
        response = post(
            client,
            f"/admin/locations/{place.id}",
            {"action": "save", "code": place.code, "city": "Geneva", "country_code": "CH", "region_id": region_id},
        )
        assert response.status_code == 400
        assert "Choose a region from the list." in text_of(response)
    assert fresh(db, Location, place.id).region_id == emea.id
    assert entries(db) == []


def test_a_location_in_a_retired_region_keeps_its_region_when_saved(
    client, logged_in_admin, db, region_factory, location_factory
):
    old = region_factory("OLD", retired=True)
    region_factory("EMEA")
    place = location_factory(old)
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "code": place.code, "city": "Basel", "country_code": "CH", "region_id": str(old.id)},
    )
    assert response.status_code == 302
    assert fresh(db, Location, place.id).city == "Basel"


def test_entries_in_use_cannot_be_deleted_only_retired(
    client,
    logged_in_admin,
    db,
    region_factory,
    location_factory,
    team_factory,
    business_line_factory,
    tracker_factory,
):
    region = region_factory("EMEA")
    covered = region_factory("APAC")
    place = location_factory(region)
    team_factory("A", location_id=place.id)
    line = business_line_factory()
    tracker = tracker_factory(business_line_id=line.id)
    db.add(TrackerRegion(tracker_id=tracker.id, region_id=covered.id))
    db.commit()

    response = post(client, f"/admin/regions/{region.id}", {"action": "delete"})
    assert response.status_code == 400
    assert "This region has locations or trackers, so it can only be retired." in text_of(response)
    response = post(client, f"/admin/regions/{covered.id}", {"action": "delete"})
    assert response.status_code == 400
    assert "This region has locations or trackers, so it can only be retired." in text_of(response)
    response = post(client, f"/admin/locations/{place.id}", {"action": "delete"})
    assert response.status_code == 400
    assert "Teams use this location, so it can only be retired." in text_of(response)
    response = post(client, f"/admin/business-lines/{line.id}", {"action": "delete"})
    assert response.status_code == 400
    assert "Trackers use this business line, so it can only be retired." in text_of(response)
    assert fresh(db, Region, region.id) and fresh(db, Region, covered.id)
    assert fresh(db, Location, place.id) and fresh(db, BusinessLine, line.id)
    assert entries(db) == []

    for url in (f"/admin/regions/{region.id}", f"/admin/locations/{place.id}", f"/admin/business-lines/{line.id}"):
        assert post(client, url, {"action": "retire"}).status_code == 302
    assert fresh(db, Region, region.id).retired is True
    assert fresh(db, Location, place.id).retired is True
    assert fresh(db, BusinessLine, line.id).retired is True
    assert [e.action for e in entries(db)] == ["region_retired", "location_retired", "business_line_retired"]
    assert [e.detail for e in entries(db)] == [
        {"region": "EMEA"},
        {"location": "Geneva, Switzerland", "region": "EMEA"},
        {"business_line": "Tradition brokerage"},
    ]

    unused_id = region_factory("LATAM").id
    assert post(client, f"/admin/regions/{unused_id}", {"action": "delete"}).status_code == 302
    assert fresh(db, Region, unused_id) is None
    deleted = entries(db, "region_deleted")[0]
    assert (deleted.entity_id, deleted.detail) == (str(unused_id), {"region": "LATAM"})


def test_unused_locations_and_business_lines_delete(
    client, logged_in_admin, db, region_factory, location_factory, business_line_factory
):
    region = region_factory()
    place_id = location_factory(region).id
    line_id = business_line_factory("TraditionData").id
    assert post(client, f"/admin/locations/{place_id}", {"action": "delete"}).status_code == 302
    assert post(client, f"/admin/business-lines/{line_id}", {"action": "delete"}).status_code == 302
    assert fresh(db, Location, place_id) is None and fresh(db, BusinessLine, line_id) is None
    assert [(e.action, e.detail) for e in entries(db)] == [
        ("location_deleted", {"location": "Geneva, Switzerland", "region": "EMEA"}),
        ("business_line_deleted", {"business_line": "TraditionData"}),
    ]


def test_delete_is_offered_only_for_unused_entries(
    client, logged_in_admin, region_factory, location_factory, team_factory
):
    region = region_factory("EMEA")
    empty = region_factory("APAC")
    used = location_factory(region)
    team_factory("A", location_id=used.id)
    page = client.get("/admin/regions").get_data(as_text=True)

    def has_delete(url: str) -> bool:
        return f'action="{url}" data-confirm=' in page

    assert has_delete(f"/admin/regions/{empty.id}")
    assert not has_delete(f"/admin/regions/{region.id}")


def test_unknown_entries_and_actions(client, logged_in_admin, region_factory):
    region = region_factory()
    assert post(client, "/admin/regions/999999", {"action": "retire"}).status_code == 404
    assert post(client, "/admin/locations/999999", {"action": "retire"}).status_code == 404
    assert post(client, "/admin/business-lines/999999", {"action": "retire"}).status_code == 404
    assert post(client, f"/admin/regions/{region.id}", {"action": "explode"}).status_code == 400


def test_retired_entries_show_a_badge_and_restore(
    client, logged_in_admin, db, region_factory, location_factory, business_line_factory
):
    region = region_factory("EMEA", retired=True)
    place = location_factory(region, retired=True)
    line = business_line_factory(retired=True)
    page = text_of(client.get("/admin/regions"))
    row = row_of(page, f"region-{region.id}")
    assert page.count(">Retired</span>") == 1 and ">Retired</span>" in row
    assert 'name="action" value="restore"' in row and "Restore the region EMEA</span></button>" in row
    assert 'value="retire"' not in row
    page = text_of(client.get("/admin/business-lines"))
    assert ">Retired</span>" in page and ">Restore</button>" in page
    for url in (f"/admin/regions/{region.id}", f"/admin/locations/{place.id}", f"/admin/business-lines/{line.id}"):
        assert post(client, url, {"action": "restore"}).status_code == 302
    assert fresh(db, Region, region.id).retired is False
    assert fresh(db, Location, place.id).retired is False
    assert fresh(db, BusinessLine, line.id).retired is False
    assert [e.action for e in entries(db)] == ["region_restored", "location_restored", "business_line_restored"]
    assert ">Retired</span>" not in text_of(client.get("/admin/regions"))


def test_retiring_a_region_keeps_its_locations_active(client, logged_in_admin, db, region_factory, location_factory):
    region = region_factory()
    place = location_factory(region)
    assert post(client, f"/admin/regions/{region.id}", {"action": "retire"}).status_code == 302
    assert fresh(db, Location, place.id).retired is False


def test_saving_unchanged_writes_no_entry(
    client, logged_in_admin, db, region_factory, location_factory, business_line_factory
):
    region = region_factory("EMEA", "Europe")
    place = location_factory(region)
    line = business_line_factory()
    for url, data in (
        (f"/admin/regions/{region.id}", {"action": "save", "code": " EMEA ", "name": "Europe"}),
        (
            f"/admin/locations/{place.id}",
            {"action": "save", "code": place.code, "city": "Geneva", "country_code": "CH", "region_id": str(region.id)},
        ),
        (f"/admin/business-lines/{line.id}", {"action": "save", "name": "Tradition brokerage"}),
    ):
        response = post(client, url, data, follow_redirects=True)
        assert response.status_code == 200
        assert NO_CHANGES_MESSAGE in text_of(response)
    assert entries(db) == []


# --- The Regions table and its dialogs ------------------------------------------------------------------------------


def test_regions_table_lists_counts_and_status(client, logged_in_admin, region_factory, location_factory, team_factory):
    emea = region_factory("EMEA", "Europe, Middle East and Africa")
    old = region_factory("OLD", "Old region", retired=True)
    london = location_factory(emea, "London", "GB", code="LON")
    location_factory(emea, "Geneva", "CH", code="GVA")
    team_factory("A", location_id=london.id)
    team_factory("B")  # placed nowhere: counted in no region
    page = client.get("/admin/regions").get_data(as_text=True)
    row = row_of(page, f"region-{emea.id}")
    assert cells_of(row)[:5] == ["EMEA", "Europe, Middle East and Africa", "2", "1", "Active"]
    assert cells_of(row_of(page, f"region-{old.id}"))[:5] == ["OLD", "Old region", "0", "0", "Retired"]
    assert page.index(f'id="region-{emea.id}"') < page.index(f'id="region-{old.id}"')
    assert 'data-search="emea europe, middle east and africa"' in row and 'data-status="active"' in row
    assert 'data-status="retired"' in row_of(page, f"region-{old.id}")
    for attribute in ('data-sort-code="EMEA"', 'data-sort-locations="2"', 'data-sort-teams="1"'):
        assert attribute in row
    assert 'data-sort-name="Europe, Middle East and Africa"' in row and 'data-sort-status="active"' in row
    edit = json.loads(html.unescape(re.search(r"data-edit='([^']*)'", row).group(1)))
    assert edit == {"code": "EMEA", "name": "Europe, Middle East and Africa", "action": f"/admin/regions/{emea.id}"}
    assert 'href="/admin/teams"' in row
    assert f'href="/admin/regions/{emea.id}/edit" data-dialog-open="edit"' in row
    assert 'href="/admin/regions/new" data-dialog-open="add"' in page
    for column in ("Code", "Name", "Locations", "Teams", "Status"):
        assert f'data-sort="{column.lower()}" hidden' in page
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    assert "Showing 2 of 2 regions" in text and "1 active" in text


def test_regions_table_says_when_there_are_none(client, logged_in_admin):
    page = text_of(client.get("/admin/regions"))
    assert "No regions yet. Add the first one." in page and "<table" not in page


def test_region_delete_only_when_unused(client, logged_in_admin, db, region_factory, location_factory, tracker_factory):
    placed, covered, unused = region_factory("EMEA"), region_factory("APAC"), region_factory("LATAM")
    location_factory(placed)
    db.add(TrackerRegion(tracker_id=tracker_factory().id, region_id=covered.id))
    db.commit()
    page = client.get("/admin/regions").get_data(as_text=True)
    for region in (placed, covered):
        row = row_of(page, f"region-{region.id}")
        assert 'value="delete"' not in row and 'value="retire"' in row
    row = row_of(page, f"region-{unused.id}")
    confirm = "Delete the region LATAM? This cannot be undone."
    assert f'action="/admin/regions/{unused.id}" data-confirm="{confirm}"' in row
    assert 'name="action" value="delete"' in row and "Delete the region LATAM</span></button>" in row


def test_new_region_page_opens_add_dialog(client, logged_in_admin, region_factory):
    region_factory("EMEA")
    response = client.get("/admin/regions/new")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    tag, dialog = dialog_of(page, "add")
    assert is_open(tag) and "data-reopen" in tag
    assert not is_open(dialog_of(page, "edit")[0])
    assert ">Add region</h2>" in dialog and 'action="/admin/regions"' in dialog
    assert 'name="code" value=""' in dialog and 'name="name" value=""' in dialog
    assert "A short name such as EMEA, at most 20 characters." in dialog
    assert ">Create region</button>" in dialog and 'href="/admin/regions"' in dialog and ">Cancel</a>" in dialog
    assert "<table" in page  # the table stays beneath the dialog


def test_edit_region_page_opens_filled_edit_dialog(client, logged_in_admin, region_factory):
    region_factory("APAC")
    region = region_factory("EMEA", "Europe, Middle East and Africa")
    response = client.get(f"/admin/regions/{region.id}/edit")
    assert response.status_code == 200
    page = text_of(response)
    tag, dialog = dialog_of(page, "edit")
    assert is_open(tag) and "data-reopen" in tag
    assert not is_open(dialog_of(page, "add")[0])
    assert "Edit region EMEA</h2>" in dialog and f'action="/admin/regions/{region.id}"' in dialog
    assert 'name="code" value="EMEA"' in dialog and 'name="name" value="Europe, Middle East and Africa"' in dialog
    assert 'name="action" value="save"' in dialog and ">Save</button>" in dialog and ">Cancel</a>" in dialog


def test_edit_dialog_is_closed_and_empty_on_the_list(client, logged_in_admin, region_factory):
    region_factory("EMEA")
    page = client.get("/admin/regions").get_data(as_text=True)
    for name in ("add", "edit"):
        tag, dialog = dialog_of(page, name)
        assert not is_open(tag) and "data-reopen" not in tag
    dialog = dialog_of(page, "edit")[1]
    assert 'name="code" value=""' in dialog and 'name="name" value=""' in dialog
    assert page.count('<dialog id="add-dialog"') == 1 and page.count('<dialog id="edit-dialog"') == 1
    ids = re.findall(r'\sid="([^"]+)"', page)
    assert len(ids) == len(set(ids))


def test_edit_unknown_region_is_404(client, logged_in_admin):
    assert client.get("/admin/regions/999999/edit").status_code == 404
    assert client.get("/admin/regions/99999999999999999999/edit").status_code == 404


def test_add_error_reopens_add_dialog_with_typed_values(client, logged_in_admin, db, region_factory):
    region_factory("EMEA")
    response = post(client, "/admin/regions", {"code": "emea", "name": "Typed <name>"})
    assert response.status_code == 400
    page = response.get_data(as_text=True)
    tag, dialog = dialog_of(page, "add")
    assert is_open(tag) and "data-reopen" in tag and not is_open(dialog_of(page, "edit")[0])
    assert 'value="emea"' in dialog and 'value="Typed &lt;name&gt;"' in dialog
    assert REGION_CODE_TAKEN in dialog
    assert 'aria-invalid="true"' in dialog and 'aria-describedby="add-code-help add-code-error"' in dialog
    assert len(db.scalars(select(Region)).all()) == 1


def test_edit_error_reopens_edit_dialog_for_that_region(client, logged_in_admin, db, region_factory):
    region_factory("EMEA")
    apac = region_factory("APAC", "Asia Pacific")
    response = post(client, f"/admin/regions/{apac.id}", {"action": "save", "code": " ", "name": "Typed name"})
    assert response.status_code == 400
    page = text_of(response)
    tag, dialog = dialog_of(page, "edit")
    assert is_open(tag) and "data-reopen" in tag and not is_open(dialog_of(page, "add")[0])
    assert f'action="/admin/regions/{apac.id}"' in dialog and "Edit region APAC</h2>" in dialog
    assert 'name="code" value=""' in dialog and 'value="Typed name"' in dialog
    assert REGION_CODE_REQUIRED in dialog
    assert fresh(db, Region, apac.id).name == "Asia Pacific"


def test_other_errors_show_above_the_table(client, logged_in_admin, region_factory, location_factory):
    region = region_factory("EMEA")
    location_factory(region)
    response = post(client, f"/admin/regions/{region.id}", {"action": "delete"})
    assert response.status_code == 400
    page = text_of(response)
    assert page.index("This region has locations or trackers, so it can only be retired.") < page.index("<table")
    for name in ("add", "edit"):
        assert not is_open(dialog_of(page, name)[0])


def test_regions_page_has_no_inline_script_or_style(client, logged_in_admin, region_factory, location_factory):
    region = region_factory("EMEA")
    region_factory("OLD", retired=True)
    location_factory(region)
    pages = [client.get(url) for url in ("/admin/regions", "/admin/regions/new", f"/admin/regions/{region.id}/edit")]
    pages.append(post(client, "/admin/regions", {"code": "", "name": ""}))
    for response in pages:
        page = response.get_data(as_text=True)
        assert re.findall(r"<script(?![^>]*\ssrc=)", page) == []
        assert " style=" not in page
        assert re.search(r"\son[a-z]+\s*=", page) is None


def _add_location(client, region, code="GVA", city="Geneva", country_code="CH"):
    return post(
        client,
        f"/admin/regions/{region.id}/locations",
        {"code": code, "city": city, "country_code": country_code},
    )


def test_location_code_is_trimmed_and_upper_cased(client, logged_in_admin, db, region_factory):
    region = region_factory()
    assert _add_location(client, region, " lon ", "London", " gb ").status_code == 302
    location = db.scalars(select(Location)).one()
    assert (location.code, location.country_code) == ("LON", "GB")


@pytest.mark.parametrize("code", ["L", "LONDONX", "L0N", "LO N"])
def test_location_code_format(client, logged_in_admin, db, region_factory, code):
    response = _add_location(client, region_factory(), code)
    assert response.status_code == 400
    assert LOCATION_CODE_FORMAT in text_of(response)
    assert db.scalars(select(Location)).all() == []


def test_location_code_taken_ignoring_case(client, logged_in_admin, db, region_factory, location_factory):
    region = region_factory()
    location_factory(region, "Geneva", "CH", code="GVA")
    response = _add_location(client, region, "Gva", "Zurich")
    assert response.status_code == 400
    assert LOCATION_CODE_TAKEN in text_of(response)
    assert len(db.scalars(select(Location)).all()) == 1


def test_location_country_required_and_listed(client, logged_in_admin, db, region_factory):
    region = region_factory()
    response = _add_location(client, region, country_code="")
    assert response.status_code == 400 and COUNTRY_REQUIRED in text_of(response)
    response = _add_location(client, region, country_code="ZZ")
    assert response.status_code == 400 and COUNTRY_CHOICE_ERROR in text_of(response)
    assert db.scalars(select(Location)).all() == []


def test_same_city_and_country_refused(client, logged_in_admin, db, region_factory, location_factory):
    region = region_factory()
    location_factory(region, "Geneva", "CH")
    response = _add_location(client, region, "GVB", "geneva", "CH")
    assert response.status_code == 400
    assert LOCATION_TAKEN in text_of(response)


def test_same_city_other_country_allowed(client, logged_in_admin, db, region_factory, location_factory):
    region = region_factory()
    location_factory(region, "London", "GB")
    assert _add_location(client, region, "LDN", "London", "CA").status_code == 302
    assert len(db.scalars(select(Location)).all()) == 2


def test_old_location_without_code_must_get_one_on_save(client, logged_in_admin, db, region_factory, location_factory):
    region = region_factory()
    place = location_factory(region, "Geneva", None, code=None)
    place.code = None
    db.commit()
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "code": "", "city": "Geneva", "country_code": "", "region_id": str(region.id)},
    )
    assert response.status_code == 400
    page = text_of(response)
    assert LOCATION_CODE_REQUIRED in page and COUNTRY_REQUIRED in page


def test_old_location_without_code_can_retire_restore_delete(
    client, logged_in_admin, db, region_factory, location_factory
):
    region = region_factory()
    place = location_factory(region, "Geneva", None)
    place.code = None
    db.commit()
    for action in ("retire", "restore"):
        assert post(client, f"/admin/locations/{place.id}", {"action": action}).status_code == 302
    assert post(client, f"/admin/locations/{place.id}", {"action": "delete"}).status_code == 302
    assert fresh(db, Location, place.id) is None


def test_location_activity_names_code_and_country(client, logged_in_admin, db, region_factory, location_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    place = location_factory(emea, "London", "GB", code="LON")
    assert _add_location(client, emea, "PAR", "Paris", "FR").status_code == 302
    assert entries(db, "location_created")[0].detail == {"location": "Paris, France", "code": "PAR", "region": "EMEA"}
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "code": "ldn", "city": "London", "country_code": "CA", "region_id": str(apac.id)},
    )
    assert response.status_code == 302
    assert entries(db, "location_changed")[0].detail == {
        "location": "London, United Kingdom",
        "before": {"code": "LON", "country": "United Kingdom", "region": "EMEA"},
        "after": {"code": "LDN", "country": "Canada", "region": "APAC"},
        "teams": 0,
    }


# --- Business lines -------------------------------------------------------------------------------------------------


def test_business_lines_add_rename_and_log(client, logged_in_admin, db, business_line_factory, tracker_factory):
    response = post(client, "/admin/business-lines", {"name": " TraditionData "})
    assert response.status_code == 302
    line = db.scalars(select(BusinessLine)).one()
    assert line.name == "TraditionData"
    tracker_factory(business_line_id=line.id)
    response = post(client, f"/admin/business-lines/{line.id}", {"action": "save", "name": "Tradition Data"})
    assert response.status_code == 302
    assert fresh(db, BusinessLine, line.id).name == "Tradition Data"
    logged = entries(db)
    assert [(e.action, e.entity, e.entity_id) for e in logged] == [
        ("business_line_created", "business_line", str(line.id)),
        ("business_line_changed", "business_line", str(line.id)),
    ]
    assert logged[0].detail == {"business_line": "TraditionData"}
    assert logged[1].detail == {
        "business_line": "TraditionData",
        "before": {"name": "TraditionData"},
        "after": {"name": "Tradition Data"},
    }
    page = text_of(client.get("/admin/business-lines"))
    assert "<h1>Business lines</h1>" in page and "Every tracker belongs to one business line." in page
    assert "<title>Business lines · Progress Tracker</title>" in page
    assert "1 tracker" in page


def test_business_line_name_is_required_and_limited(client, logged_in_admin, db, business_line_factory):
    response = post(client, "/admin/business-lines", {"name": ""})
    assert response.status_code == 400 and "Enter a business line name." in text_of(response)
    response = post(client, "/admin/business-lines", {"name": "x" * 101})
    assert response.status_code == 400
    assert "A business line name can be at most 100 characters." in text_of(response)
    line = business_line_factory()
    response = post(client, f"/admin/business-lines/{line.id}", {"action": "save", "name": " "})
    assert response.status_code == 400 and "Enter a business line name." in text_of(response)
    assert entries(db) == []


# --- Navigation and labels ------------------------------------------------------------------------------------------


def test_nav_shows_the_lists_to_administrators_only(client, logged_in_user, give_set, db, user_factory):
    give_set(["manage_teams", "manage_users"], user=logged_in_user)
    page = client.get("/").get_data(as_text=True)
    assert 'href="/admin/regions"' not in page and 'href="/admin/business-lines"' not in page
    assert 'data-label="Regions"' not in page

    from tests.conftest import sign_in

    sign_in(client, user_factory(is_admin=True))
    page = client.get("/admin/regions").get_data(as_text=True)
    assert 'href="/admin/regions"' in page and 'href="/admin/business-lines"' in page
    assert 'data-label="Regions"' in page and "<span>Regions</span>" in page and "Business lines" in page
    assert "Regions and locations" not in page
    assert page.index('href="/admin/teams"') < page.index('href="/admin/regions"')
    assert page.index('href="/admin/regions"') < page.index('href="/admin/business-lines"')
    assert 'class="nav-link active" href="/admin/regions"' in page
    page = client.get("/admin/business-lines").get_data(as_text=True)
    assert 'class="nav-link active" href="/admin/business-lines"' in page


def test_activity_labels_for_the_lists():
    from tracker.activity.labels import action_label

    for prefix, noun in (("region", "Region"), ("location", "Location"), ("business_line", "Business line")):
        assert action_label(f"{prefix}_created") == f"{noun} added"
        assert action_label(f"{prefix}_changed") == f"{noun} changed"
        assert action_label(f"{prefix}_retired") == f"{noun} retired"
        assert action_label(f"{prefix}_restored") == f"{noun} restored"
        assert action_label(f"{prefix}_deleted") == f"{noun} deleted"


def test_used_regions_offer_retire_or_restore_but_no_delete(
    client, logged_in_admin, region_factory, location_factory, team_factory
):
    region = region_factory("OLD", retired=True)
    team_factory("A", location_id=location_factory(region).id)
    active = region_factory("EMEA")
    team_factory("B", location_id=location_factory(active, "Zurich").id)
    page = text_of(client.get("/admin/regions"))
    retired_row, active_row = row_of(page, f"region-{region.id}"), row_of(page, f"region-{active.id}")
    assert 'value="restore"' in retired_row and 'value="retire"' in active_row
    assert 'value="delete"' not in retired_row and 'value="delete"' not in active_row
    assert "This region has locations or trackers, so it can only be retired." not in page
