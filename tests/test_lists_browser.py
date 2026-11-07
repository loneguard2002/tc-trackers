"""The Regions and Locations tables in a real browser, under the Content Security Policy (database): search, status
and region filters, sorting, and the Add and Edit dialogs that lists.js opens as modals."""

from __future__ import annotations

import re

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from sqlalchemy import func, select
from test_report_page_browser import RECORDER

from tracker.models import Location, Region

pytestmark = pytest.mark.browser

ROWS = "#locations-table tbody tr:visible"


def _open(page, live_server, admin, url):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}{url}")


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def _names(page, table="locations-table"):
    return page.locator(f"#{table} tbody tr:visible .list-name").all_inner_texts()


def _chip(page, status):
    return page.locator(f'[data-status-for] button[data-status="{status}"] [data-count]')


def _foot(page):
    return " ".join(page.locator(".list-foot").inner_text().split())


def _is_modal(page, dialog_id):
    return page.evaluate(f"document.getElementById('{dialog_id}').matches(':modal')")


def _location_count(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Location))


@pytest.fixture
def places(region_factory, location_factory, team_factory):
    """EMEA, APAC and OLD (retired); London (2 teams), Geneva (retired), Singapore (1 team), Tokyo (retired)."""
    emea = region_factory("EMEA", "Europe, Middle East and Africa")
    apac = region_factory("APAC", "Asia Pacific")
    old = region_factory("OLD", "Old region", retired=True)
    lon = location_factory(emea, "London", "GB", code="LON")
    gva = location_factory(emea, "Geneva", "CH", code="GVA", retired=True)
    sin = location_factory(apac, "Singapore", "SG", code="SIN")
    tyo = location_factory(apac, "Tokyo", "JP", code="TYO", retired=True)
    for name in ("London desk", "London rates"):
        team_factory(name, location_id=lon.id)
    team_factory("Asia desk", location_id=sin.id)
    return {"emea": emea, "apac": apac, "old": old, "lon": lon, "gva": gva, "sin": sin, "tyo": tyo}


# --- Search, filters and sorting -------------------------------------------------------------------------------------


def test_search_filters_rows_and_counts(page, live_server, user_factory, region_factory, location_factory):
    emea = region_factory("EMEA", "Europe, Middle East and Africa")
    apac = region_factory("APAC", "Asia Pacific")
    location_factory(emea, "London", "GB", code="LON")
    location_factory(emea, "Geneva", "CH", code="GVA")
    location_factory(apac, "Singapore", "SG", code="SIN")
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    search = page.locator("#locations-table-search")
    expect(search).to_be_visible()
    expect(page.locator("[data-status-for]")).to_be_visible()
    expect(page.locator("#locations-table-region")).to_be_visible()
    expect(page.locator(".sort-button").first).to_be_visible()
    expect(page.locator("th [data-sort-label]").first).to_be_hidden()
    expect(_chip(page, "all")).to_have_text("3")
    expect(_chip(page, "active")).to_have_text("3")
    expect(_chip(page, "retired")).to_have_text("0")

    search.fill("lon")
    expect(page.locator(ROWS)).to_have_count(1)
    assert _names(page) == ["London"]
    assert _foot(page) == "Showing 1 of 3 locations 3 active"  # every active row, whatever is shown
    expect(_chip(page, "all")).to_have_text("1")
    expect(_chip(page, "active")).to_have_text("1")

    search.fill("SWITZERLAND")  # the country name, ignoring case
    assert _names(page) == ["Geneva"]
    search.fill("asia pacific")  # the region name
    assert _names(page) == ["Singapore"]
    search.fill("")
    expect(page.locator(ROWS)).to_have_count(3)
    assert _foot(page) == "Showing 3 of 3 locations 3 active"
    _clean(page)


def test_search_with_special_characters_is_plain_text(
    page, live_server, user_factory, region_factory, location_factory
):
    emea = region_factory("EMEA")
    amer = region_factory("AMER")
    location_factory(amer, "São Paulo", "BR", code="SAO")
    location_factory(emea, "St. Gallen", "CH", code="STG")
    location_factory(emea, "Stockholm", "SE", code="STO")
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    search = page.locator("#locations-table-search")
    for text, names in (
        ("(", []),
        ("[", []),
        ("\\", []),
        (".*", []),
        ("São", ["São Paulo"]),
        ("St.", ["St. Gallen"]),
        ("st", ["St. Gallen", "Stockholm"]),
    ):
        search.fill(text)
        expect(page.locator(ROWS)).to_have_count(len(names))
        assert sorted(_names(page)) == names, text
        expect(_chip(page, "all")).to_have_text(str(len(names)))
    _clean(page)


def test_status_and_region_filters_combine(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    retired = page.locator('[data-status-for] button[data-status="retired"]')
    retired.click()
    expect(retired).to_have_attribute("aria-pressed", "true")
    expect(page.locator('[data-status-for] button[data-status="all"]')).to_have_attribute("aria-pressed", "false")
    assert sorted(_names(page)) == ["Geneva", "Tokyo"]
    assert _foot(page) == "Showing 2 of 4 locations 2 active"  # the active count ignores the filters
    page.select_option("#locations-table-region", str(places["apac"].id))
    assert _names(page) == ["Tokyo"]
    # The counts follow the region filter: APAC has one active and one retired location.
    expect(_chip(page, "all")).to_have_text("2")
    expect(_chip(page, "active")).to_have_text("1")
    expect(_chip(page, "retired")).to_have_text("1")
    assert _foot(page) == "Showing 1 of 4 locations 2 active"
    page.locator('[data-status-for] button[data-status="active"]').click()
    assert _names(page) == ["Singapore"]
    page.select_option("#locations-table-region", "")
    assert sorted(_names(page)) == ["London", "Singapore"]
    _clean(page)


def test_sorting_toggles_and_sets_aria_sort(page, live_server, user_factory, places, team_factory):
    for n in range(9):  # Singapore 10 teams, London 2: numbers sort as numbers, not as text
        team_factory(f"Asia team {n}", location_id=places["sin"].id)
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    name = page.locator("th").filter(has=page.locator('button[data-sort="name"]'))
    code = page.locator("th").filter(has=page.locator('button[data-sort="code"]'))
    name.locator("button").click()
    expect(name).to_have_attribute("aria-sort", "ascending")
    assert _names(page) == ["Geneva", "London", "Singapore", "Tokyo"]
    name.locator("button").click()
    expect(name).to_have_attribute("aria-sort", "descending")
    assert _names(page) == ["Tokyo", "Singapore", "London", "Geneva"]
    expect(code).to_have_attribute("aria-sort", "none")

    teams = page.locator("th").filter(has=page.locator('button[data-sort="teams"]'))
    teams.locator("button").focus()
    page.keyboard.press("Enter")  # the sort buttons work from the keyboard
    expect(teams).to_have_attribute("aria-sort", "ascending")
    expect(name).to_have_attribute("aria-sort", "none")
    assert _names(page)[-2:] == ["London", "Singapore"]
    teams.locator("button").click()
    assert _names(page)[0] == "Singapore"
    _clean(page)


def test_region_query_presets_filter(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), f"/admin/locations?region={places['apac'].id}")

    expect(page.locator("#locations-table-region")).to_have_value(str(places["apac"].id))
    assert sorted(_names(page)) == ["Singapore", "Tokyo"]
    assert _foot(page) == "Showing 2 of 4 locations 2 active"
    _clean(page)


def test_regions_table_search_and_sort(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/regions")

    page.locator("#regions-table-search").fill("asia")
    assert _names(page, "regions-table") == ["Asia Pacific"]
    assert _foot(page) == "Showing 1 of 3 regions 2 active"
    page.locator("#regions-table-search").fill("")
    page.locator('[data-status-for] button[data-status="retired"]').click()
    assert _names(page, "regions-table") == ["Old region"]
    page.locator('[data-status-for] button[data-status="all"]').click()
    page.locator('button[data-sort="code"]').click()  # already in code order, so the first click reverses it
    assert _names(page, "regions-table") == ["Old region", "Europe, Middle East and Africa", "Asia Pacific"]
    page.locator('button[data-sort="code"]').click()
    assert _names(page, "regions-table") == ["Asia Pacific", "Europe, Middle East and Africa", "Old region"]
    _clean(page)


@pytest.mark.parametrize(
    "url, table, default, first_click",
    [
        # Server order: region code, then city. Descending by region keeps the cities in the server's order.
        ("/admin/locations", "locations-table", "region", ["Geneva", "London", "Singapore", "Tokyo"]),
        ("/admin/regions", "regions-table", "code", ["Old region", "Europe, Middle East and Africa", "Asia Pacific"]),
    ],
)
def test_the_server_order_column_starts_sorted(
    page, live_server, user_factory, places, url, table, default, first_click
):
    _open(page, live_server, user_factory(is_admin=True), url)

    headers = page.locator(f"#{table} thead th:has(button.sort-button)")
    expect(headers.first).to_have_attribute("aria-sort", re.compile("."))
    states = headers.evaluate_all(
        "hs => hs.map(h => [h.querySelector('button').dataset.sort, h.getAttribute('aria-sort')])"
    )
    assert {key: state for key, state in states if state != "none"} == {default: "ascending"}
    page.locator(f'#{table} button[data-sort="{default}"]').click()
    expect(page.locator(f"#{table} th:has(button[data-sort='{default}'])")).to_have_attribute("aria-sort", "descending")
    assert _names(page, table) == first_click
    _clean(page)


def test_a_line_says_when_nothing_matches(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    note = page.locator("[data-no-match]")
    expect(note).to_be_hidden()
    page.locator("#locations-table-search").fill("zzz")
    expect(page.locator(ROWS)).to_have_count(0)
    expect(note).to_be_visible()
    expect(note).to_have_text("No locations match.")
    assert _foot(page) == "Showing 0 of 4 locations 2 active"
    page.locator("#locations-table-search").fill("")
    expect(note).to_be_hidden()
    page.select_option("#locations-table-region", str(places["old"].id))  # OLD has no locations
    expect(note).to_be_visible()
    page.select_option("#locations-table-region", "")
    expect(note).to_be_hidden()

    page.goto(f"{live_server}/admin/regions")
    page.locator("#regions-table-search").fill("zzz")
    expect(page.locator("[data-no-match]")).to_have_text("No regions match.")
    expect(page.locator("[data-no-match]")).to_be_visible()
    _clean(page)


# --- Dialogs ----------------------------------------------------------------------------------------------------------


def test_add_dialog_is_modal_and_creates(page, live_server, db, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.get_by_role("link", name="Add location").click()
    expect(page.locator("#add-dialog")).to_be_visible()
    assert _is_modal(page, "add-dialog")
    assert page.url.endswith("/admin/locations")
    expect(page.locator("#add-region")).to_be_focused()
    page.select_option("#add-region", str(places["apac"].id))
    page.fill("#add-code", "TPE")
    page.fill("#add-city", "Taipei")
    page.select_option("#add-country", "TW")
    page.locator("#add-dialog").get_by_role("button", name="Create location").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Added the location Taipei")
    expect(page.locator("#locations-table")).to_contain_text("TPE")
    expect(page.locator("#add-dialog")).to_be_hidden()
    assert _location_count(db) == 5
    _clean(page)


def test_add_dialog_clears_what_an_earlier_error_left(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.get_by_role("link", name="Add location").click()
    page.select_option("#add-region", str(places["emea"].id))
    page.fill("#add-code", "L0N")
    page.fill("#add-city", "Leeds")
    page.select_option("#add-country", "GB")
    page.locator("#add-dialog").get_by_role("button", name="Create location").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator("#add-dialog")).to_be_visible()
    assert _is_modal(page, "add-dialog")
    expect(page.locator("#add-code")).to_be_focused()  # the first field with an error
    expect(page.locator("#add-code-error")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#add-dialog")).to_be_hidden()
    page.get_by_role("link", name="Add location").click()
    expect(page.locator("#add-code")).to_have_value("")
    expect(page.locator("#add-city")).to_have_value("")
    expect(page.locator("#add-region")).to_have_value("")
    expect(page.locator("#add-country")).to_have_value("")
    expect(page.locator("#add-dialog .country-flag-preview")).to_be_hidden()
    expect(page.locator("#add-dialog .field-error")).to_have_count(0)
    expect(page.locator("#add-dialog .form-alert")).to_have_count(0)
    assert page.locator("#add-code").get_attribute("aria-invalid") is None
    _clean(page)


def test_add_after_an_error_shows_the_help_again(page, live_server, user_factory, places):
    """While the code has an error the help is hidden (the error repeats it); the next Add brings the help back."""
    _open(page, live_server, user_factory(is_admin=True), "/admin/regions")

    page.get_by_role("link", name="Add region").click()
    page.fill("#add-code", "emea")  # taken
    page.fill("#add-name", "Elsewhere")
    page.locator("#add-dialog").get_by_role("button", name="Create region").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator("#add-code-error")).to_be_visible()
    expect(page.locator("#add-code-help")).to_be_hidden()
    expect(page.locator("#add-code")).to_have_attribute("aria-describedby", "add-code-error")
    page.locator("#add-dialog").get_by_role("link", name="Cancel").click()
    page.get_by_role("link", name="Add region").click()
    expect(page.locator("#add-code-error")).to_have_count(0)
    expect(page.locator("#add-code-help")).to_be_visible()
    expect(page.locator("#add-code")).to_have_attribute("aria-describedby", "add-code-help")
    _clean(page)


def test_edit_dialog_fills_from_row(page, live_server, user_factory, places):
    lon = places["lon"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.locator(f"#location-{lon.id} a.row-edit").click()
    dialog = page.locator("#edit-dialog")
    expect(dialog).to_be_visible()
    assert _is_modal(page, "edit-dialog")
    assert page.url.endswith("/admin/locations")
    expect(page.locator("#edit-dialog-title")).to_have_text("Edit location LON")
    expect(page.locator("#edit-code")).to_have_value("LON")
    expect(page.locator("#edit-city")).to_have_value("London")
    expect(page.locator("#edit-region")).to_have_value(str(places["emea"].id))
    expect(page.locator("#edit-country")).to_have_value("GB")
    assert page.locator("#edit-dialog .country-flag-preview").get_attribute("src").endswith("/flags/gb.svg")
    expect(page.locator("#edit-dialog .country-flag-preview")).to_be_visible()
    assert page.locator("#edit-dialog form").get_attribute("action") == f"/admin/locations/{lon.id}"
    expect(page.locator("#edit-region-note")).to_have_text("Used by 2 teams. Changing the region moves them to it.")
    expect(page.locator("#edit-region-note")).to_be_visible()
    expect(page.locator("#edit-region")).to_be_focused()

    page.locator("#edit-dialog").get_by_role("link", name="Cancel").click()
    expect(dialog).to_be_hidden()
    page.locator(f"#location-{places['sin'].id} a.row-edit").click()
    expect(page.locator("#edit-region-note")).to_have_text(
        "Used by 1 team. Changing the region moves the team with it."
    )
    page.locator("#edit-dialog").get_by_role("link", name="Close").click()
    page.locator(f"#location-{places['gva'].id} a.row-edit").click()
    expect(page.locator("#edit-region-note")).to_be_hidden()
    expect(page.locator("#edit-region-note")).to_have_text("")
    _clean(page)


def test_edit_saves_to_the_row_it_opened_for(page, live_server, db, user_factory, places):
    lon, sin = places["lon"], places["sin"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.locator(f"#location-{lon.id} a.row-edit").click()
    page.keyboard.press("Escape")
    expect(page.locator("#edit-dialog")).to_be_hidden()
    page.locator(f"#location-{sin.id} a.row-edit").click()
    page.fill("#edit-city", "Singapore City")
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Saved the location Singapore City")
    db.expire_all()
    assert db.get(Location, sin.id).city == "Singapore City"
    assert db.get(Location, lon.id).city == "London"
    assert _location_count(db) == 4
    _clean(page)


def test_edit_without_an_action_follows_the_link(page, live_server, user_factory, places):
    lon = places["lon"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.evaluate(
        """id => { const row = document.getElementById(id); const data = JSON.parse(row.dataset.edit);
        delete data.action; row.dataset.edit = JSON.stringify(data); }""",
        f"location-{lon.id}",
    )
    page.locator(f"#location-{lon.id} a.row-edit").click()
    page.wait_for_url(f"**/admin/locations/{lon.id}/edit")
    expect(page.locator("#edit-code")).to_have_value("LON")
    _clean(page)


def test_edit_error_reopens_modal_edit_dialog(page, live_server, db, user_factory, places):
    lon = places["lon"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.locator(f"#location-{lon.id} a.row-edit").click()
    page.fill("#edit-code", "L0N")
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator("#edit-dialog")).to_be_visible()
    assert _is_modal(page, "edit-dialog")
    expect(page.locator("#edit-code-error")).to_contain_text("2 to 6 letters")
    expect(page.locator("#edit-code")).to_have_value("L0N")
    expect(page.locator("#edit-code")).to_be_focused()
    expect(page.locator("#add-dialog")).to_be_hidden()
    assert page.url.endswith(f"/admin/locations/{lon.id}")  # where the form was sent
    page.locator("#edit-dialog").get_by_role("link", name="Cancel").click()
    expect(page.locator("#edit-dialog")).to_be_hidden()
    # Closed without leaving the page; the address is the table's again, so a reload does not reopen the dialog.
    expect(page).to_have_url(re.compile(r"/admin/locations$"))
    page.reload()
    expect(page.locator("#edit-dialog")).to_be_hidden()
    db.expire_all()
    assert db.get(Location, lon.id).code == "LON"
    _clean(page)


def test_escape_after_a_region_edit_error_restores_the_address(page, live_server, db, user_factory, places):
    emea = places["emea"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/regions")

    page.locator(f"#region-{emea.id} a.row-edit").click()
    page.fill("#edit-code", "apac")  # taken
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("#edit-code-error")).to_be_visible()
    assert page.url.endswith(f"/admin/regions/{emea.id}")
    page.keyboard.press("Escape")
    expect(page.locator("#edit-dialog")).to_be_hidden()
    expect(page).to_have_url(re.compile(r"/admin/regions$"))
    db.expire_all()
    assert db.get(Region, emea.id).code == "EMEA"
    _clean(page)


def test_edit_offers_each_location_its_own_retired_region(
    page, live_server, db, user_factory, region_factory, location_factory
):
    region_factory("EMEA")
    first = region_factory("ONE", "First old region", retired=True)
    second = region_factory("TWO", "Second old region", retired=True)
    basel = location_factory(first, "Basel", "CH", code="BSL")
    bern = location_factory(second, "Bern", "CH", code="BRN")
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    # An error on Bern (region TWO) brings the page back from the server with Bern's Edit dialog open.
    page.locator(f"#location-{bern.id} a.row-edit").click()
    page.fill("#edit-code", "B3RN")
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("#edit-code-error")).to_be_visible()
    expect(page.locator("#edit-region")).to_have_value(str(second.id))
    page.keyboard.press("Escape")

    page.locator(f"#location-{basel.id} a.row-edit").click()
    expect(page.locator("#edit-region")).to_have_value(str(first.id))
    states = page.eval_on_selector_all(
        "#edit-region option[data-retired]", "os => os.map(o => [o.value, o.hidden, o.disabled])"
    )
    assert sorted(states) == sorted([[str(first.id), False, False], [str(second.id), True, True]])
    expect(page.locator("#edit-code-error")).to_have_count(0)
    page.fill("#edit-city", "Basle")
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Saved the location Basle")
    db.expire_all()
    saved = db.get(Location, basel.id)
    assert (saved.city, saved.region_id) == ("Basle", first.id)
    assert db.get(Location, bern.id).code == "BRN"
    _clean(page)


def test_country_change_updates_flag(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    page.get_by_role("link", name="Add location").click()
    preview = page.locator("#add-dialog .country-flag-preview")
    expect(preview).to_be_hidden()
    page.select_option("#add-country", label="Switzerland (CH)")
    expect(preview).to_be_visible()
    assert preview.get_attribute("src").endswith("/flags/ch.svg")
    page.select_option("#add-country", "")
    expect(preview).to_be_hidden()
    _clean(page)


def test_region_dialogs_add_and_edit(page, live_server, db, user_factory, places):
    emea = places["emea"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/regions")

    page.locator(f"#region-{emea.id} a.row-edit").click()
    assert _is_modal(page, "edit-dialog")
    expect(page.locator("#edit-dialog-title")).to_have_text("Edit region EMEA")
    expect(page.locator("#edit-code")).to_have_value("EMEA")
    expect(page.locator("#edit-name")).to_have_value("Europe, Middle East and Africa")
    expect(page.locator("#edit-code")).to_be_focused()
    page.fill("#edit-name", "Europe")
    page.locator("#edit-dialog").get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".flash")).to_contain_text("Saved the region EMEA")

    page.get_by_role("link", name="Add region").click()
    assert _is_modal(page, "add-dialog")
    page.fill("#add-code", "AMER")
    page.fill("#add-name", "Americas")
    page.locator("#add-dialog").get_by_role("button", name="Create region").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".flash")).to_contain_text("Added the region AMER")
    db.expire_all()
    assert db.get(Region, emea.id).name == "Europe"
    assert db.scalar(select(func.count()).select_from(Region)) == 4
    _clean(page)


def test_new_page_reopens_its_dialog_as_a_modal(page, live_server, user_factory, places):
    _open(page, live_server, user_factory(is_admin=True), "/admin/regions/new")

    expect(page.locator("#add-dialog")).to_be_visible()
    assert _is_modal(page, "add-dialog")
    expect(page.locator("#add-code")).to_be_focused()
    page.locator("#add-dialog").get_by_role("link", name="Close").click()
    expect(page.locator("#add-dialog")).to_be_hidden()
    expect(page).to_have_url(re.compile(r"/admin/regions$"))
    _clean(page)


def test_delete_still_asks_first(page, live_server, db, user_factory, places):
    tyo = places["tyo"]
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    messages = []

    def accept(dialog):
        messages.append(dialog.message)
        dialog.accept()

    page.on("dialog", accept)
    page.locator(f"#location-{tyo.id}").get_by_role("button", name=re.compile("^Delete")).click()
    page.wait_for_load_state("networkidle")
    assert len(messages) == 1
    assert "Delete the location" in messages[0] and "Tokyo, Japan" in messages[0]
    expect(page.locator(f"#location-{tyo.id}")).to_have_count(0)
    expect(page.locator(".flash")).to_contain_text("Deleted the location Tokyo")
    assert _location_count(db) == 3
    _clean(page)


def test_business_line_add_dialog_is_modal_and_creates(page, live_server, db, user_factory, business_line_factory):
    business_line_factory("Brokerage")
    _open(page, live_server, user_factory(is_admin=True), "/admin/business-lines")

    page.get_by_role("link", name="Add business line").click()
    expect(page.locator("#add-dialog")).to_be_visible()
    assert _is_modal(page, "add-dialog")
    assert page.url.endswith("/admin/business-lines")
    expect(page.locator("#add-name")).to_be_focused()
    page.fill("#add-name", "Data")
    page.locator("#add-dialog").get_by_role("button", name="Create business line").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Added the business line Data")
    assert _names(page, "business-lines-table") == ["Brokerage", "Data"]
    _clean(page)


def test_business_lines_search_filter_and_edit(page, live_server, user_factory, business_line_factory):
    business_line_factory("Brokerage")
    business_line_factory("Data")
    business_line_factory("Legacy", retired=True)
    _open(page, live_server, user_factory(is_admin=True), "/admin/business-lines")

    page.locator("#business-lines-table-search").fill("da")
    assert _names(page, "business-lines-table") == ["Data"]
    page.locator("#business-lines-table-search").fill("")
    page.locator('[data-status-for] button[data-status="retired"]').click()
    assert _names(page, "business-lines-table") == ["Legacy"]
    assert _foot(page) == "Showing 1 of 3 business lines 2 active"
    page.locator('[data-status-for] button[data-status="all"]').click()
    page.get_by_role("link", name="Edit Data").click()
    assert _is_modal(page, "edit-dialog")
    expect(page.locator("#edit-name")).to_have_value("Data")
    _clean(page)


# --- Layout -----------------------------------------------------------------------------------------------------------


def test_no_horizontal_scroll_at_390(page, live_server, user_factory, places):
    page.set_viewport_size({"width": 390, "height": 900})
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")
    for url in ("/admin/locations", "/admin/regions", "/admin/business-lines"):
        page.goto(f"{live_server}{url}")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, url
        tabs = page.locator("nav.tabs a.tab")
        assert tabs.count() == 3
        for index in range(3):  # every tab is fully on screen, with no scrolling of the bar
            box = tabs.nth(index).bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390, (url, index, box)
        assert page.evaluate("document.querySelector('nav.tabs').scrollLeft") == 0, url
        page.locator("a[data-dialog-open=add]").click()
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, url
    _clean(page)


def test_status_buttons_stay_left_when_wrapped(page, live_server, user_factory, places):
    page.set_viewport_size({"width": 390, "height": 900})
    _open(page, live_server, user_factory(is_admin=True), "/admin/locations")

    search = page.locator("[data-search-for]").bounding_box()
    region = page.locator("#locations-table-region").bounding_box()
    status = page.locator("[data-status-for]").bounding_box()
    assert status["y"] > region["y"] > search["y"]  # each on a line of its own
    assert abs(status["x"] - search["x"]) < 1
    assert abs(region["x"] - search["x"]) < 1 and abs(region["width"] - search["width"]) < 1
    _clean(page)


def test_region_access_role_autosubmits(page, live_server, db, user_factory, region_factory, region_grant):
    from tracker.models import RegionGrant

    region = region_factory("EMEA", "Europe, Middle East and Africa")
    holder = user_factory(full_name="Holder One")
    region_grant(region, holder, "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/regions/{region.id}/access")

    expect(page.locator("[data-autosubmit-fallback]")).to_be_hidden()  # the select saves by itself
    page.select_option(f"#role-{holder.id}", "editor")
    expect(page.get_by_text("Holder One now has Editor access to EMEA.")).to_be_visible()
    db.expire_all()
    assert db.scalar(select(RegionGrant.role).where(RegionGrant.user_id == holder.id)) == "editor"
    _clean(page)

    page.set_viewport_size({"width": 390, "height": 800})
    assert page.evaluate("document.scrollingElement.scrollWidth") <= 390


# --- Paging and status tokens (shown on the team page tables) -------------------------------------------------------


def test_pager_pages_rows_and_resets_on_search(page, live_server, user_factory, team_factory, add_member):
    team = team_factory(name="Big team")
    for n in range(30):
        add_member(team, user_factory(full_name=f"Person {n:02d}"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{team.id}")
    rows = "#people-table tbody tr:visible"
    pager = page.locator('[data-pager-for="people-table"]')
    expect(pager).to_be_visible()
    expect(page.locator(rows)).to_have_count(25)
    expect(pager).to_contain_text("Showing 1–25 of 30 people")
    pager.get_by_role("button", name="Next").click()
    expect(page.locator(rows)).to_have_count(5)
    expect(pager).to_contain_text("Showing 26–30 of 30 people")
    page.get_by_role("searchbox", name="Search people").fill("person 0")
    expect(pager).to_contain_text("Showing 1–10 of 10 people")
    page.get_by_role("searchbox", name="Search people").fill("")
    expect(page.locator(rows)).to_have_count(25)
    pager.get_by_role("button", name="Next").click()
    pager.get_by_label("Rows per page").select_option("50")
    expect(page.locator(rows)).to_have_count(30)
    expect(pager).to_contain_text("Showing 1–30 of 30 people")
    page.set_viewport_size({"width": 390, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    _clean(page)


def test_status_tokens_match_a_row_in_two_groups(page, live_server, user_factory, team_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    both = user_factory(full_name="Bea Both")
    add_member(infra, both, "owner")
    add_member(windows, both, "viewer")
    add_member(windows, user_factory(full_name="Dan Direct"), "viewer")
    add_member(infra, user_factory(full_name="Ian Inherited"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")
    names = "#people-table tbody tr:visible .member-name"
    page.locator("button[data-status=direct]").click()
    assert sorted(n.split(" (")[0] for n in page.locator(names).all_inner_texts()) == ["Bea Both", "Dan Direct"]
    page.locator("button[data-status=inherited]").click()
    assert sorted(page.locator(names).all_inner_texts()) == ["Bea Both", "Ian Inherited"]
    expect(page.locator("button[data-status=all]")).to_contain_text("3")
    _clean(page)


def test_people_filter_counts_leave_out_people_who_are_not_active(
    page, live_server, user_factory, team_factory, add_member
):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(windows, user_factory(full_name="Dan Direct"), "viewer")
    add_member(windows, user_factory(full_name="Dora Disabled", status="disabled"), "viewer")
    add_member(infra, user_factory(full_name="Ian Inherited"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")
    for status, count in (("all", "2"), ("direct", "1"), ("inherited", "1")):
        expect(_chip(page, status)).to_have_text(count)
    page.locator("button[data-status=direct]").click()
    names = page.locator("#people-table tbody tr:visible .member-name").all_inner_texts()
    assert sorted(n.split()[0] for n in names) == ["Dan", "Dora"]  # Dora is still listed
    page.locator("#people-table-search").fill("d")
    expect(_chip(page, "direct")).to_have_text("1")
    _clean(page)


def test_pager_says_tracker_for_one_row(page, live_server, user_factory, team_factory, tracker_factory):
    team = team_factory(name="Infrastructure")
    tracker_factory(name="Only one", team_id=team.id)
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{team.id}?tab=trackers")
    pager = page.locator('[data-pager-for="trackers-table"]')
    expect(pager).to_contain_text("Showing 1\u20131 of 1 tracker")
    assert "trackers" not in pager.locator(".pager-count").inner_text()
    _clean(page)


def test_pager_keeps_keyboard_focus_on_the_current_page(page, live_server, user_factory, team_factory, add_member):
    team = team_factory(name="Big team")
    for n in range(60):
        add_member(team, user_factory(full_name=f"Person {n:02d}"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{team.id}")
    pager = page.locator('[data-pager-for="people-table"]')
    pager.get_by_role("button", name="Page 2", exact=True).focus()
    page.keyboard.press("Enter")
    expect(pager).to_contain_text("Showing 26\u201350 of 60 people")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Page 2"
    assert page.evaluate("document.activeElement.getAttribute('aria-current')") == "page"
    pager.get_by_role("button", name="Page 3", exact=True).focus()
    page.keyboard.press("Enter")  # the last page: Next becomes disabled
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Page 3"
    pager.get_by_role("button", name="Previous").focus()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Page 2"
    _clean(page)


def test_picker_and_trackers_table_keep_separate_no_match_lines(
    page, live_server, user_factory, team_factory, tracker_factory
):
    team = team_factory(name="Infrastructure")
    other = team_factory(name="Applications")
    tracker_factory(name="Inside one", team_id=team.id)
    tracker_factory(name="Outside one", team_id=other.id)
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{team.id}?tab=trackers&add=1")
    picker = page.locator("#pick-table").locator("xpath=ancestor::form")
    page.get_by_role("searchbox", name="Search trackers to add").fill("zzz")
    expect(picker.locator("[data-no-match]")).to_be_visible()
    expect(
        page.locator("#trackers-table")
        .locator("xpath=ancestor::*[contains(@class,'list-table')]")
        .locator("[data-no-match]")
    ).to_be_hidden()
    assert page.locator("[data-no-match]:visible").count() == 1
    page.get_by_role("searchbox", name="Search trackers", exact=True).fill("zzz")
    assert page.locator("[data-no-match]:visible").count() == 2
    page.get_by_role("searchbox", name="Search trackers to add").fill("")
    assert page.locator("[data-no-match]:visible").count() == 1
    _clean(page)
