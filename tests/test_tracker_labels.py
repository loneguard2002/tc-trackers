"""Trackers have a business line and regions: the New tracker, Settings and import-confirm fields, their checks and
the Activity details."""

import html
import re
from io import BytesIO

from sqlalchemy import select

from tests.conftest import post
from tests.importer.build_fixture import workbook_bytes
from tests.test_trackers import SETTINGS
from tracker.importer import create_tracker_from_preview, read_workbook
from tracker.lists.catalogue import (
    BUSINESS_LINE_CHOICE_ERROR,
    BUSINESS_LINE_REQUIRED,
    REGIONS_CHOICE_ERROR,
    REGIONS_REQUIRED,
    TrackerLabels,
    set_tracker_regions,
    tracker_labels,
)
from tracker.models import AuditLog, Tracker

REGIONS_HELP = (
    "Choose every region the tracker covers. In a later release, people given a region will see its trackers, so "
    "changing the regions changes who can see this tracker."
)


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def labels_of(db, tracker) -> TrackerLabels:
    db.expire_all()
    return tracker_labels(db, [tracker.id])[tracker.id]


def labels(line, *regions) -> dict:
    return {"business_line_id": str(line.id), "region_ids": [str(r.id) for r in regions]}


def selected_line(page: str) -> str | None:
    select_html = re.search(r'<select id="business_line_id".*?</select>', page, re.S).group(0)
    match = re.search(r'<option value="(\d*)"[^>]*\sselected', select_html)
    return match.group(1) if match else None


def ticked_regions(page: str) -> list[str]:
    return re.findall(r'<input[^>]*name="region_ids" value="(\d+)"[^>]*\schecked', page)


def labelled(db, tracker, line, *regions) -> None:
    tracker.business_line_id = line.id
    set_tracker_regions(db, tracker.id, [r.id for r in regions])
    db.commit()


def test_a_new_tracker_needs_a_business_line_and_a_region(
    client, logged_in_admin, db, region_factory, business_line_factory
):
    emea, line = region_factory("EMEA"), business_line_factory()
    page = post(client, "/trackers/new", SETTINGS)
    text = page.get_data(as_text=True)
    assert page.status_code == 400 and "Choose a business line." in text and "Tick at least one region." in text
    response = post(
        client, "/trackers/new", {**SETTINGS, "business_line_id": str(line.id), "region_ids": [str(emea.id)]}
    )
    assert response.status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert tracker_labels(db, [tracker.id])[tracker.id] == TrackerLabels("Tradition brokerage", ["EMEA"])
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "tracker_created")).one()
    assert entry.detail["business_line"] == "Tradition brokerage" and entry.detail["regions"] == ["EMEA"]


def test_the_new_tracker_form_offers_the_lists_and_keeps_the_choice(
    client, logged_in_admin, db, region_factory, business_line_factory
):
    emea, apac = region_factory("EMEA", "Europe"), region_factory("APAC", "Asia Pacific")
    region_factory("OLD", retired=True)
    line = business_line_factory()
    business_line_factory("Gone", retired=True)
    page = client.get("/trackers/new")
    body = text_of(page)
    assert '<option value="" selected>Choose a business line</option>' in body
    assert "Tradition brokerage" in body and "Gone" not in body
    assert "APAC – Asia Pacific" in body and "EMEA – Europe" in body and "OLD" not in body
    assert REGIONS_HELP in body and "<legend" in body
    assert ticked_regions(page.get_data(as_text=True)) == []
    assert 'src="/static/tracker-new.js' in body
    refused = post(client, "/trackers/new", {**SETTINGS, "name": "  ", **labels(line, emea, apac)})
    raw = refused.get_data(as_text=True)
    assert refused.status_code == 400 and BUSINESS_LINE_REQUIRED not in raw and REGIONS_REQUIRED not in raw
    assert selected_line(raw) == str(line.id) and sorted(ticked_regions(raw)) == sorted([str(emea.id), str(apac.id)])
    assert db.scalars(select(Tracker)).first() is None


def test_a_new_tracker_refuses_unknown_or_retired_choices(
    client, logged_in_admin, db, region_factory, business_line_factory
):
    emea, old_region = region_factory("EMEA"), region_factory("OLD", retired=True)
    line, old_line = business_line_factory(), business_line_factory("Gone", retired=True)
    for bad in (
        {"business_line_id": str(old_line.id), "region_ids": [str(emea.id)]},
        {"business_line_id": "9999", "region_ids": [str(emea.id)]},
    ):
        page = post(client, "/trackers/new", {**SETTINGS, **bad})
        assert page.status_code == 400 and BUSINESS_LINE_CHOICE_ERROR in text_of(page)
    for bad in ([str(old_region.id)], ["9999"], ["abc"]):
        page = post(client, "/trackers/new", {**SETTINGS, "business_line_id": str(line.id), "region_ids": bad})
        assert page.status_code == 400 and REGIONS_CHOICE_ERROR in text_of(page)
    assert db.scalars(select(Tracker)).first() is None and entries(db, "tracker_created") == []


def test_an_old_tracker_shows_not_set_and_its_next_save_needs_both(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    tracker = tracker_factory(name="Old")
    region_factory("EMEA")
    business_line_factory()
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert selected_line(page) == "" and ticked_regions(page) == []
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "name": "Renamed"})
    assert response.status_code == 400
    assert BUSINESS_LINE_REQUIRED in text_of(response) and REGIONS_REQUIRED in text_of(response)
    db.expire_all()
    assert db.get(Tracker, tracker.id).name == "Old"
    assert labels_of(db, tracker) == TrackerLabels(None, []) and entries(db, "settings_updated") == []


def test_a_settings_label_error_shows_beside_the_other_errors(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    tracker = tracker_factory(name="Old")
    region_factory("EMEA")
    business_line_factory()
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "moving_average_weeks": "40"})
    body = text_of(response)
    assert response.status_code == 400 and BUSINESS_LINE_REQUIRED in body and REGIONS_REQUIRED in body
    assert "moving-average" in body.lower()


def test_changing_regions_is_logged_before_and_after(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    line, data = business_line_factory(), business_line_factory("TraditionData")
    tracker = tracker_factory(name="Rollout")
    labelled(db, tracker, line, emea)
    page = client.get(f"/trackers/{tracker.id}/settings").get_data(as_text=True)
    assert selected_line(page) == str(line.id) and ticked_regions(page) == [str(emea.id)]
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **labels(line, emea, apac)})
    assert response.status_code == 302
    assert labels_of(db, tracker) == TrackerLabels("Tradition brokerage", ["APAC", "EMEA"])
    [entry] = entries(db, "settings_updated")
    assert entry.detail["regions"] == [["EMEA"], ["APAC", "EMEA"]] and "business_line" not in entry.detail
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **labels(data, apac)})
    assert response.status_code == 302
    assert labels_of(db, tracker) == TrackerLabels("TraditionData", ["APAC"])
    latest = entries(db, "settings_updated")[-1]
    assert latest.detail == {
        "business_line": ["Tradition brokerage", "TraditionData"],
        "regions": [["APAC", "EMEA"], ["APAC"]],
    }
    assert post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **labels(data, apac)}).status_code == 302
    assert len(entries(db, "settings_updated")) == 2


def test_an_old_tracker_given_its_labels_logs_them_from_none(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    emea, line = region_factory("EMEA"), business_line_factory()
    tracker = tracker_factory(name="Rollout")
    assert post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **labels(line, emea)}).status_code == 302
    [entry] = entries(db, "settings_updated")
    assert entry.detail["business_line"] == [None, "Tradition brokerage"] and entry.detail["regions"] == [[], ["EMEA"]]


def test_saving_with_a_retired_business_line_and_region_keeps_them(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    old_region, old_line = region_factory("OLD", "Old region"), business_line_factory("Gone")
    tracker = tracker_factory(name="Rollout")
    labelled(db, tracker, old_line, old_region)
    old_region.retired = old_line.retired = True
    db.commit()
    page = client.get(f"/trackers/{tracker.id}/settings")
    raw, body = page.get_data(as_text=True), text_of(page)
    assert "Gone (retired)" in body and "OLD – Old region (retired)" in body
    assert selected_line(raw) == str(old_line.id) and ticked_regions(raw) == [str(old_region.id)]
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, **labels(old_line, old_region)})
    assert response.status_code == 302
    assert labels_of(db, tracker) == TrackerLabels("Gone", ["OLD"])
    [entry] = entries(db, "settings_updated")  # the other settings differ from the factory's
    assert "business_line" not in entry.detail and "regions" not in entry.detail


def confirm_token(client) -> str:
    page = post(
        client,
        "/import",
        {"weekday": "4", "workbook": (BytesIO(workbook_bytes()), "book.xlsx")},
        content_type="multipart/form-data",
    )
    body = page.get_data(as_text=True)
    assert 'name="business_line_id"' in body and 'name="region_ids"' in body and REGIONS_HELP in html.unescape(body)
    return body.split('name="payload" value="')[1].split('"')[0]


def test_import_confirmation_asks_for_both(client, logged_in_admin, db, region_factory, business_line_factory):
    emea, apac, line = region_factory("EMEA"), region_factory("APAC"), business_line_factory()
    token = confirm_token(client)
    refused = post(client, "/import/confirm", {"payload": token, "name": "Rollout"})
    assert refused.status_code == 400
    assert BUSINESS_LINE_REQUIRED in text_of(refused) and REGIONS_REQUIRED in text_of(refused)
    assert db.scalars(select(Tracker)).first() is None
    kept = post(client, "/import/confirm", {"payload": token, "name": "Rollout", "business_line_id": str(line.id)})
    raw = kept.get_data(as_text=True)
    assert kept.status_code == 400 and BUSINESS_LINE_REQUIRED not in raw and selected_line(raw) == str(line.id)
    done = post(client, "/import/confirm", {"payload": token, "name": "Rollout", **labels(line, emea, apac)})
    assert done.status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert labels_of(db, tracker) == TrackerLabels("Tradition brokerage", ["APAC", "EMEA"])
    [entry] = entries(db, "tracker_imported")
    assert entry.detail["business_line"] == "Tradition brokerage" and entry.detail["regions"] == ["APAC", "EMEA"]


def test_new_tracker_team_options_carry_their_region(
    client, logged_in_admin, db, team_factory, region_factory, location_factory
):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    placed = team_factory(name="Desktop", location_id=geneva.id)
    team_factory(name="Unplaced")
    page = client.get("/trackers/new").get_data(as_text=True)
    assert re.search(rf'<option value="{placed.id}" data-region="{emea.id}"', page)
    assert page.count("data-region=") == 1


def test_a_workbook_imported_without_the_labels_leaves_them_not_set(db, user_factory):
    """The command-line import cannot ask, so it passes neither and the tracker shows them as not set."""
    admin = user_factory(is_admin=True)
    tracker = create_tracker_from_preview(
        db, read_workbook(BytesIO(workbook_bytes()), 4), "Rollout", "", "", admin.id, False
    )
    db.commit()
    assert labels_of(db, tracker) == TrackerLabels(None, [])
    [entry] = entries(db, "tracker_imported")
    assert entry.detail["business_line"] is None and entry.detail["regions"] == []
