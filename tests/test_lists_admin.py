"""Administration screens for regions, locations and business lines (database required)."""

import html

from sqlalchemy import select

from tests.conftest import post
from tracker.audit import NO_CHANGES_MESSAGE
from tracker.lists.catalogue import team_places
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


# --- Access ---------------------------------------------------------------------------------------------------------


def test_lists_are_for_administrators_only(client, logged_in_user, give_set, db, region_factory, location_factory):
    give_set(["manage_teams", "manage_users"], user=logged_in_user)
    for url in ("/admin/regions", "/admin/business-lines"):
        assert client.get(url).status_code == 403
    assert post(client, "/admin/regions", {"code": "EMEA", "name": "Europe"}).status_code == 403
    region = region_factory("APAC")
    location = location_factory(region)
    for url, data in (
        (f"/admin/regions/{region.id}", {"action": "delete"}),
        (f"/admin/regions/{region.id}/locations", {"city": "Tokyo", "country": "Japan"}),
        (f"/admin/locations/{location.id}", {"action": "retire"}),
        ("/admin/business-lines", {"name": "Brokerage"}),
    ):
        assert post(client, url, data).status_code == 403
    assert db.scalar(select(Region.code).where(Region.id == region.id)) == "APAC"
    assert entries(db) == []


def test_lists_send_signed_out_visitors_to_sign_in(client):
    response = client.get("/admin/regions")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


# --- Regions and locations ------------------------------------------------------------------------------------------


def test_admin_adds_a_region_and_a_location_and_both_are_logged(client, logged_in_admin, db):
    response = post(client, "/admin/regions", {"code": " EMEA ", "name": "Europe, Middle East and Africa"})
    assert response.status_code == 302
    region = db.scalars(select(Region)).one()
    assert (region.code, region.name, region.retired) == ("EMEA", "Europe, Middle East and Africa", False)
    response = post(client, f"/admin/regions/{region.id}/locations", {"city": " Geneva ", "country": "Switzerland"})
    assert response.status_code == 302
    location = db.scalars(select(Location)).one()
    assert (location.region_id, location.city, location.country) == (region.id, "Geneva", "Switzerland")
    logged = entries(db)
    assert [e.action for e in logged] == ["region_created", "location_created"]
    assert [e.entity for e in logged] == ["region", "location"]
    assert [e.entity_id for e in logged] == [str(region.id), str(location.id)]
    assert all(e.tracker_id is None and e.user_id == logged_in_admin.id for e in logged)
    assert logged[0].detail == {"region": "EMEA"}
    assert logged[1].detail == {"location": "Geneva, Switzerland", "region": "EMEA"}
    page = text_of(client.get("/admin/regions"))
    assert "<h1>Regions and locations</h1>" in page
    lede = "Teams are placed at a location, and each location belongs to one region."
    assert f"{lede} Trackers say which regions they cover." in page
    assert "Europe, Middle East and Africa" in page and "Geneva, Switzerland" in page
    assert "<title>Regions and locations · Progress Tracker</title>" in page


def test_regions_and_locations_are_listed_in_order_ignoring_case(
    client, logged_in_admin, region_factory, location_factory
):
    emea, apac = region_factory("emea"), region_factory("APAC")
    location_factory(emea, "zurich", "Switzerland")
    location_factory(emea, "Geneva", "Switzerland")
    location_factory(emea, "london", "United Kingdom")
    page = text_of(client.get("/admin/regions"))
    assert page.index(apac.name) < page.index(emea.name)
    assert page.index("Geneva, Switzerland") < page.index("london, United Kingdom") < page.index("zurich, Switzerland")
    assert "No locations in this region yet." in page  # APAC


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
    response = post(client, f"/admin/regions/{region.id}/locations", {"city": "", "country": " "})
    assert response.status_code == 400
    page = text_of(response)
    assert "Enter a city." in page and "Enter a country." in page
    response = post(client, f"/admin/regions/{region.id}/locations", {"city": "x" * 101, "country": "y" * 101})
    assert response.status_code == 400
    page = text_of(response)
    assert "A city can be at most 100 characters." in page and "A country can be at most 100 characters." in page
    assert db.scalars(select(Location)).all() == []
    assert post(client, "/admin/regions/999999/locations", {"city": "Tokyo", "country": "Japan"}).status_code == 404


def test_duplicate_names_are_refused_ignoring_case(
    client, logged_in_admin, db, region_factory, location_factory, business_line_factory
):
    emea = region_factory("EMEA", "Europe, Middle East and Africa")
    apac = region_factory("APAC")
    location_factory(emea, "Geneva", "Switzerland")
    business_line_factory("Tradition brokerage")
    response = post(client, "/admin/regions", {"code": "emea", "name": "europe, middle east and africa"})
    assert response.status_code == 400
    page = text_of(response)
    assert "A region with that short name already exists." in page
    assert "A region with that name already exists." in page
    response = post(client, f"/admin/regions/{apac.id}/locations", {"city": "geneva", "country": "SWITZERLAND"})
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
    page = client.get("/admin/regions").get_data(as_text=True)
    assert "Used by 2 teams. Changing the region moves them to it." in page
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "city": "Geneva", "country": "Switzerland", "region_id": str(apac.id)},
    )
    assert response.status_code == 302
    db.expire_all()
    assert {p.region_code for p in team_places(db).values()} == {"APAC"}
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "location_changed")).one()
    assert entry.detail["teams"] == 2
    assert entry.detail["before"] == {"region": "EMEA"} and entry.detail["after"] == {"region": "APAC"}
    assert entry.detail["location"] == "Geneva, Switzerland"


def test_team_count_help_is_singular_and_omitted_without_teams(
    client, logged_in_admin, region_factory, location_factory, team_factory
):
    region = region_factory()
    used = location_factory(region)
    location_factory(region, "Zurich")
    team_factory("A", location_id=used.id)
    page = text_of(client.get("/admin/regions"))
    assert "Used by 1 team. Changing the region moves the team with it." in page
    assert "Changing the region moves them to it." not in page


def test_renaming_a_location_logs_without_a_team_count(
    client, logged_in_admin, db, region_factory, location_factory, team_factory
):
    region = region_factory()
    place = location_factory(region)
    team_factory("A", location_id=place.id)
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "city": "Genève", "country": "Switzerland", "region_id": str(region.id)},
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
            {"action": "save", "city": "Geneva", "country": "Switzerland", "region_id": region_id},
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
    page = client.get("/admin/regions").get_data(as_text=True)
    assert f'<option value="{old.id}" selected>' in page
    response = post(
        client,
        f"/admin/locations/{place.id}",
        {"action": "save", "city": "Basel", "country": "Switzerland", "region_id": str(old.id)},
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
    spare = location_factory(region, "Zurich")
    team_factory("A", location_id=used.id)
    page = client.get("/admin/regions").get_data(as_text=True)

    def has_delete(url: str) -> bool:
        return f'action="{url}" data-confirm=' in page

    assert has_delete(f"/admin/regions/{empty.id}") and has_delete(f"/admin/locations/{spare.id}")
    assert not has_delete(f"/admin/regions/{region.id}") and not has_delete(f"/admin/locations/{used.id}")
    assert "1 team" in text_of(client.get("/admin/regions"))


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
    assert page.count(">Retired</span>") == 2 and ">Restore</button>" in page
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
            {"action": "save", "city": "Geneva", "country": "Switzerland", "region_id": str(region.id)},
        ),
        (f"/admin/business-lines/{line.id}", {"action": "save", "name": "Tradition brokerage"}),
    ):
        response = post(client, url, data, follow_redirects=True)
        assert response.status_code == 200
        assert NO_CHANGES_MESSAGE in text_of(response)
    assert entries(db) == []


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
    assert "Regions and locations" not in page

    from tests.conftest import sign_in

    sign_in(client, user_factory(is_admin=True))
    page = client.get("/admin/regions").get_data(as_text=True)
    assert 'href="/admin/regions"' in page and 'href="/admin/business-lines"' in page
    assert "Regions and locations" in page and "Business lines" in page
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


def test_in_use_note_is_not_shown_beside_restore(
    client, logged_in_admin, region_factory, location_factory, team_factory
):
    region = region_factory("OLD", retired=True)
    team_factory("A", location_id=location_factory(region).id)
    retired_page = text_of(client.get("/admin/regions"))
    assert "Restore" in retired_page
    assert "Teams use this location, so it can only be retired." in retired_page
    assert "This region has locations or trackers, so it can only be retired." not in retired_page
    active = region_factory("EMEA")
    team_factory("B", location_id=location_factory(active, "Zurich").id)
    assert "This region has locations or trackers, so it can only be retired." in text_of(client.get("/admin/regions"))
