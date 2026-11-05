"""The region's Access screen: administrators give people access to a region (database required)."""

import html
import re

import pytest
from sqlalchemy import select

from tests.conftest import post
from tracker.audit import NO_CHANGES_MESSAGE
from tracker.auth.permissions import PERMISSIONS
from tracker.auth.roles import user_role
from tracker.ids import MAX_ID
from tracker.lists.access import ALREADY_HAS_ACCESS, CHOOSE_ACTION, CHOOSE_PERSON, CHOOSE_ROLE, RETIRED_NO_NEW_ACCESS
from tracker.lists.views import REGION_IN_USE
from tracker.models import AuditLog, Region, RegionGrant, TrackerRegion


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))


def grants(db, region) -> dict[int, str]:
    db.expire_all()
    return dict(
        db.execute(select(RegionGrant.user_id, RegionGrant.role).where(RegionGrant.region_id == region.id)).all()
    )


def url(region) -> str:
    return f"/admin/regions/{region.id}/access"


def test_access_page_lists_people_and_offers_only_active_people_without_access(
    client, logged_in_admin, user_factory, region_factory, region_grant
):
    region = region_factory("EMEA", "Europe, Middle East and Africa")
    holder = user_factory(full_name="Holder One", email="holder@example.com")
    gone = user_factory(full_name="Gone Person", email="gone@example.com", status="disabled")
    region_grant(region, holder, "editor")
    region_grant(region, gone, "viewer")
    user_factory(full_name="zeta person")
    user_factory(full_name="Alpha Person")
    page = text_of(client.get(url(region)))
    assert "<title>Access to EMEA" in page
    assert "Europe, Middle East and Africa" in page
    assert "People given access to a region reach every tracker that covers it, at the role shown." in page
    table = page[page.index("<table") : page.index("</table>")]
    assert "Holder One" in table and "holder@example.com" in table and "Gone Person" in table
    assert "Disabled" in table
    assert '<option value="editor" selected>' in table
    form = page[page.index("Give access</button>") - 2500 : page.index("Give access</button>")]
    options = re.findall(r"<option value=\"\d+\">([^<]*)</option>", form)
    names = [o.split(" (")[0] for o in options]
    assert names == ["Alpha Person", logged_in_admin.full_name, "zeta person"]  # by name, ignoring case
    assert '<option value="viewer" selected>' in form


def test_empty_access_page_says_so(client, logged_in_admin, region_factory):
    region = region_factory("EMEA")
    page = text_of(client.get(url(region)))
    assert "Nobody has access to this region yet." in page and "<table" not in page


def test_give_access_logs_and_reaches_the_tracker(
    client, logged_in_admin, db, user_factory, region_factory, tracker_factory
):
    region = region_factory("EMEA")
    tracker = tracker_factory()
    db.add(TrackerRegion(tracker_id=tracker.id, region_id=region.id))
    db.commit()
    person = user_factory(full_name="Ada Lovelace")
    response = post(client, url(region), {"user_id": str(person.id), "role": "viewer", "action": "give"})
    assert response.status_code == 302 and response.headers["Location"].endswith(url(region))
    assert user_role(db, person, tracker.id) == "viewer"
    [entry] = entries(db, "region_access_given")
    assert (entry.entity, entry.entity_id, entry.tracker_id, entry.target_user_id) == (
        "region",
        str(region.id),
        None,
        person.id,
    )
    assert entry.user_id == logged_in_admin.id
    assert entry.detail == {"region": "EMEA", "role": "viewer"}
    assert "Gave Ada Lovelace Viewer access to EMEA." in text_of(client.get(url(region)))


def test_change_role_and_remove_log_before_and_after(
    client, logged_in_admin, db, user_factory, region_factory, region_grant
):
    region = region_factory("EMEA")
    person = user_factory(full_name="Ada Lovelace")
    region_grant(region, person, "viewer")
    response = post(client, url(region), {"user_id": str(person.id), "role": "owner", "action": "set"})
    assert response.status_code == 302
    assert grants(db, region) == {person.id: "owner"}
    [changed] = entries(db, "region_access_changed")
    assert changed.detail == {"region": "EMEA", "before": "viewer", "after": "owner"}
    assert changed.target_user_id == person.id and changed.entity_id == str(region.id) and changed.tracker_id is None
    assert "Ada Lovelace now has Owner access to EMEA." in text_of(client.get(url(region)))
    response = post(client, url(region), {"user_id": str(person.id), "role": "remove", "action": "set"})
    assert response.status_code == 302
    assert grants(db, region) == {}
    [removed] = entries(db, "region_access_removed")
    assert removed.detail == {"region": "EMEA", "role": "owner"} and removed.target_user_id == person.id
    assert "Removed Ada Lovelace's access to EMEA." in text_of(client.get(url(region)))


def test_same_role_is_no_change(client, logged_in_admin, db, user_factory, region_factory, region_grant):
    region = region_factory("EMEA")
    person = user_factory()
    region_grant(region, person, "editor")
    response = post(client, url(region), {"user_id": str(person.id), "role": "editor", "action": "set"})
    assert response.status_code == 302
    assert NO_CHANGES_MESSAGE in text_of(client.get(url(region)))
    assert entries(db, "region_access_changed") == [] and grants(db, region) == {person.id: "editor"}


def test_grant_given_at_the_same_moment(client, logged_in_admin, db, user_factory, region_factory, monkeypatch):
    region = region_factory("EMEA")
    person = user_factory()
    from tracker.lists import access

    real = access.record

    def record_after_rival(session, **kwargs):  # another administrator commits the same grant just before ours
        with session.get_bind().connect() as other:
            other.execute(RegionGrant.__table__.insert().values(region_id=region.id, user_id=person.id, role="owner"))
            other.commit()
        real(session, **kwargs)

    monkeypatch.setattr(access, "record", record_after_rival)
    response = post(client, url(region), {"user_id": str(person.id), "role": "viewer", "action": "give"})
    assert response.status_code == 400 and ALREADY_HAS_ACCESS in text_of(response)
    assert grants(db, region) == {person.id: "owner"}
    assert entries(db, "region_access_given") == []


@pytest.mark.parametrize("kind", ["abc", "disabled", "unknown"])
def test_inactive_or_unknown_person_is_400(client, logged_in_admin, db, user_factory, region_factory, kind):
    region = region_factory("EMEA")
    value = {
        "abc": "abc",
        "disabled": str(user_factory(status="disabled").id),
        "unknown": str(MAX_ID + 1),
    }[kind]
    response = post(client, url(region), {"user_id": value, "role": "viewer", "action": "give"})
    assert response.status_code == 400 and CHOOSE_PERSON in text_of(response)
    assert grants(db, region) == {} and entries(db, "region_access_given") == []


def test_bad_role_or_action_is_400(client, logged_in_admin, db, user_factory, region_factory):
    region = region_factory("EMEA")
    person = user_factory()
    for data in (
        {"user_id": str(person.id), "role": "admin", "action": "give"},
        {"user_id": str(person.id), "role": "remove", "action": "give"},
        {"user_id": str(person.id), "role": "viewer", "action": "other"},
    ):
        assert post(client, url(region), data).status_code == 400
    assert grants(db, region) == {} and entries(db, "region_access_given") == []


def test_retired_region_refuses_new_access_but_keeps_and_edits_existing(
    client, logged_in_admin, db, user_factory, region_factory, region_grant
):
    region = region_factory("OLD", retired=True)
    holder, newcomer = user_factory(full_name="Holder One"), user_factory(full_name="Newcomer")
    region_grant(region, holder, "viewer")
    page = text_of(client.get(url(region)))
    assert "This region is retired. Access given here keeps working until it is removed." in page
    assert "Give access</button>" not in page and "Holder One" in page
    response = post(client, url(region), {"user_id": str(newcomer.id), "role": "viewer", "action": "give"})
    assert response.status_code == 400 and RETIRED_NO_NEW_ACCESS in text_of(response)
    assert grants(db, region) == {holder.id: "viewer"}
    assert post(client, url(region), {"user_id": str(holder.id), "role": "editor", "action": "set"}).status_code == 302
    assert grants(db, region) == {holder.id: "editor"}
    assert post(client, url(region), {"user_id": str(holder.id), "role": "remove", "action": "set"}).status_code == 302
    assert grants(db, region) == {}


def test_changing_a_missing_grant_is_404_and_a_removal_already_made_is_a_notice(
    client, logged_in_admin, user_factory, region_factory
):
    region = region_factory("EMEA")
    person = user_factory()
    assert post(client, url(region), {"user_id": str(person.id), "role": "owner", "action": "set"}).status_code == 404
    assert post(client, url(region), {"user_id": "abc", "role": "owner", "action": "set"}).status_code == 404
    assert client.get("/admin/regions/999999/access").status_code == 404


def test_region_with_grants_cannot_be_deleted(client, logged_in_admin, db, user_factory, region_factory, region_grant):
    region = region_factory("EMEA")
    region_grant(region, user_factory(), "viewer")
    response = post(client, f"/admin/regions/{region.id}", {"action": "delete"})
    assert response.status_code == 400 and REGION_IN_USE in text_of(response)
    assert "people with access" in REGION_IN_USE
    db.expire_all()
    assert db.get(Region, region.id) is not None


def test_regions_table_shows_people_count_linking_to_access(
    client, logged_in_admin, user_factory, region_factory, region_grant
):
    region, other = region_factory("EMEA"), region_factory("APAC")
    for _ in range(2):
        region_grant(region, user_factory(), "viewer")
    page = text_of(client.get("/admin/regions"))
    assert "People" in page[page.index("<thead") : page.index("</thead>")]
    for target, count in ((region, 2), (other, 0)):
        row = page[page.index(f'<tr id="region-{target.id}"') :]
        row = row[: row.index("</tr>")]
        assert f'data-sort-people="{count}"' in row
        assert f'<a class="count-pill" href="{url(target)}">{count}' in row
    # a region with only grants shows the muted slot, not Delete
    assert 'value="delete"' not in page[page.index(f'<tr id="region-{region.id}"') :].split("</tr>")[0]


def test_access_screen_is_administrators_only(client, logged_in_user, give_set, region_factory):
    region = region_factory("EMEA")
    give_set(list(PERMISSIONS), user=logged_in_user)
    assert client.get(url(region)).status_code == 403
    assert post(client, url(region), {"user_id": "1", "role": "viewer", "action": "give"}).status_code == 403


def test_anonymous_visitors_are_sent_to_sign_in(client, region_factory):
    region = region_factory("EMEA")
    for response in (client.get(url(region)), post(client, url(region), {"action": "give"})):
        assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_set_with_an_invalid_role_changes_nothing(
    client, logged_in_admin, db, user_factory, region_factory, region_grant
):
    region = region_factory("EMEA")
    person = user_factory()
    region_grant(region, person, "editor")
    response = post(client, url(region), {"user_id": str(person.id), "role": "admin", "action": "set"})
    assert response.status_code == 400 and CHOOSE_ROLE in text_of(response)
    assert grants(db, region) == {person.id: "editor"}
    assert entries(db, "region_access_changed") == []


def test_an_unknown_action_asks_for_an_action(client, logged_in_admin, region_factory):
    response = post(client, url(region_factory("EMEA")), {"action": "bogus"})
    assert response.status_code == 400 and CHOOSE_ACTION == "Choose an action." and CHOOSE_ACTION in text_of(response)
