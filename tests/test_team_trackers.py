"""A team's Trackers tab: moving trackers into the team (picker, access preview, confirm) and the row Remove."""

import re

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from tests.conftest import post, sign_in
from tests.test_teams import entries, flat, holder, raw_of, text_of
from tracker.auth.guards import SELF_PROMOTION_MESSAGE
from tracker.ids import MAX_ID
from tracker.models import Region, Team, Tracker, TrackerRegion
from tracker.teams import views
from tracker.teams.tracker_moves import (
    CHOOSE_TRACKERS_MESSAGE,
    TEAM_DELETED_MESSAGE,
    TRACKER_CHOICE_ERROR,
    TRACKERS_CHANGED_MESSAGE,
    tracker_move_impact,
)


@pytest.fixture
def setup(db, region_factory, team_factory, tracker_factory):
    """Infrastructure (EMEA) holding Network refresh; Applications (APAC) holding Laptop refresh (APAC) and the
    archived Old rollout; Payroll audit (EMEA) in no team."""
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    infra = team_factory(name="Infrastructure", region_id=emea.id)
    apps = team_factory(name="Applications", region_id=apac.id)
    inside = tracker_factory(name="Network refresh", team_id=infra.id)
    laptops = tracker_factory(name="Laptop refresh", team_id=apps.id)
    old = tracker_factory(name="Old rollout", team_id=apps.id, status="archived")
    payroll = tracker_factory(name="Payroll audit")
    db.add_all(
        [
            TrackerRegion(tracker_id=laptops.id, region_id=apac.id),
            TrackerRegion(tracker_id=payroll.id, region_id=emea.id),
        ]
    )
    db.commit()
    return {
        "emea": emea,
        "apac": apac,
        "infra": infra,
        "apps": apps,
        "inside": inside,
        "laptops": laptops,
        "old": old,
        "payroll": payroll,
    }


def moves(team) -> str:
    return f"/admin/teams/{team.id}/trackers"


def query(*trackers) -> str:
    return "&".join(f"tracker_id={t.id}" for t in trackers)


def picker_rows(raw: str) -> dict[str, str]:
    """The picker's rows by tracker name."""
    start = raw.index('id="pick-table"')
    table = raw[start : raw.index("</table>", start)]
    rows = re.findall(r"<tr data-search.*?</tr>", table, re.S)
    return {re.search(r"<label[^>]*>(.*?)</label>", row, re.S).group(1).strip(): row for row in rows}


def region_codes(db, tracker) -> set[str]:
    db.expire_all()
    return set(
        db.scalars(
            select(Region.code)
            .join(TrackerRegion, TrackerRegion.region_id == Region.id)
            .where(TrackerRegion.tracker_id == tracker.id)
        )
    )


def team_of(db, tracker) -> int | None:
    db.expire_all()
    return db.scalar(select(Tracker.team_id).where(Tracker.id == tracker.id))


# --- The picker ----------------------------------------------------------------------------------------------------


def test_picker_lists_trackers_outside_the_team_with_regions_after(client, logged_in_admin, team_factory, setup):
    infra = setup["infra"]
    tab = raw_of(client.get(f"/admin/teams/{infra.id}?tab=trackers"))
    assert f'href="/admin/teams/{infra.id}?tab=trackers&amp;add=1"' in tab and "Add trackers" in tab
    assert 'id="pick-table"' not in tab

    raw = raw_of(client.get(f"/admin/teams/{infra.id}?tab=trackers&add=1"))
    form = raw[raw.index('id="pick-form"') - 200 : raw.index("</form>", raw.index('id="pick-form"'))]
    assert 'method="get"' in form and f'action="{moves(infra)}"' in form
    assert "Move here" in flat(form)
    assert "Add trackers to Infrastructure" in flat(raw)
    rows = picker_rows(raw)
    assert set(rows) == {"Laptop refresh", "Old rollout", "Payroll audit"}  # Network refresh is already here
    for name in rows:
        tracker = setup[{"Laptop refresh": "laptops", "Old rollout": "old", "Payroll audit": "payroll"}[name]]
        assert f'name="tracker_id" value="{tracker.id}"' in rows[name]
    laptops = flat(rows["Laptop refresh"])
    assert "Applications" in laptops and "APAC" in laptops and "+ EMEA" in laptops
    payroll = flat(rows["Payroll audit"])
    assert "No team" in payroll and "EMEA" in payroll and "+ EMEA" not in payroll
    old = flat(rows["Old rollout"])
    assert "Archived" in old and "+ EMEA" in old

    nowhere = team_factory(name="Nowhere")
    rows = picker_rows(raw_of(client.get(f"/admin/teams/{nowhere.id}?tab=trackers&add=1")))
    assert set(rows) == {"Network refresh", "Laptop refresh", "Old rollout", "Payroll audit"}
    assert all("+ " not in flat(row) for row in rows.values())


def test_access_link_and_add_trackers_carry_icons(client, logged_in_admin, setup):
    raw = raw_of(client.get(f"/admin/teams/{setup['infra'].id}?tab=trackers"))
    access = re.search(r'<a [^>]*href="/trackers/\d+/roles"[^>]*>.*?</a>', raw, re.S).group(0)
    assert "<svg" in access
    add = re.search(r'<a [^>]*href="[^"]*add=1"[^>]*>.*?</a>', raw, re.S).group(0)
    assert "<svg" in add and "Add trackers" in add


# --- The preview and the move --------------------------------------------------------------------------------------


def test_preview_lists_access_changes_and_confirm_moves_and_adds_the_region(
    client, logged_in_admin, db, user_factory, add_member, region_grant, setup
):
    infra, apps, laptops, payroll = setup["infra"], setup["apps"], setup["laptops"], setup["payroll"]
    add_member(infra, user_factory(full_name="Infra Lead"), "editor")
    add_member(apps, user_factory(full_name="Apps Lead"), "owner")
    region_grant(setup["emea"], user_factory(full_name="Emea Viewer"), "viewer")

    response = client.get(f"{moves(infra)}?{query(laptops, payroll)}")
    assert response.status_code == 200
    page = flat(raw_of(response))
    assert "Move trackers to Infrastructure" in page
    assert "Infra Lead gains Editor on Laptop refresh." in page
    assert "Infra Lead gains Editor on Payroll audit." in page
    assert "Apps Lead loses Owner on Laptop refresh." in page
    assert "Emea Viewer gains Viewer on Laptop refresh." in page  # by the region it gains
    assert "Emea Viewer gains Viewer on Payroll audit." not in page  # it already covers EMEA
    assert "No roles change." in page
    raw = raw_of(response)
    moving = raw[raw.index('id="section-moving"') : raw.index("</section>", raw.index('id="section-moving"'))]
    assert "Laptop refresh" in flat(moving) and "From Applications" in flat(moving) and "+ EMEA" in flat(moving)
    assert "Payroll audit" in flat(moving) and "From no team" in flat(moving)
    form = raw[raw.index('class="move-confirm"') : raw.index("</form>", raw.index('class="move-confirm"'))]
    assert re.search(rf'<form class="move-confirm" method="post" action="{moves(infra)}">', raw)
    assert f'value="{laptops.id}"' in form and f'value="{payroll.id}"' in form
    assert "Move 2 trackers here" in flat(form)
    assert team_of(db, laptops) == apps.id and region_codes(db, laptops) == {"APAC"}
    assert entries(db) == []

    response = post(client, moves(infra), {"tracker_id": [str(laptops.id), str(payroll.id)]})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/teams/{infra.id}?tab=trackers")
    assert "Moved 2 trackers to Infrastructure." in text_of(client.get(response.headers["Location"]))
    assert team_of(db, laptops) == infra.id and team_of(db, payroll) == infra.id
    assert region_codes(db, laptops) == {"APAC", "EMEA"} and region_codes(db, payroll) == {"EMEA"}
    moved = entries(db, "tracker_team_changed")
    assert sorted((e.tracker_id, e.entity, e.entity_id) for e in moved) == sorted(
        [(laptops.id, "tracker", str(laptops.id)), (payroll.id, "tracker", str(payroll.id))]
    )
    details = {e.tracker_id: e.detail for e in moved}
    assert details[laptops.id] == {"before": "Applications", "after": "Infrastructure"}
    assert details[payroll.id] == {"before": None, "after": "Infrastructure"}
    [regions] = entries(db, "settings_updated")
    assert regions.tracker_id == laptops.id
    assert regions.detail == {"regions": [["APAC"], ["APAC", "EMEA"]]}


def test_moving_one_tracker_names_it(client, logged_in_admin, db, setup):
    infra, old = setup["infra"], setup["old"]
    page = flat(raw_of(client.get(f"{moves(infra)}?{query(old)}")))
    assert "Move 1 tracker here" in page and "Archived" in page
    response = post(client, moves(infra), {"tracker_id": str(old.id)}, follow_redirects=True)
    assert "Moved Old rollout to Infrastructure." in text_of(response)
    assert team_of(db, old) == infra.id and region_codes(db, old) == {"EMEA"}


def test_a_team_with_no_region_adds_none(client, logged_in_admin, db, team_factory, setup):
    nowhere, laptops = team_factory(name="Nowhere"), setup["laptops"]
    assert "+ " not in flat(raw_of(client.get(f"{moves(nowhere)}?{query(laptops)}")))
    post(client, moves(nowhere), {"tracker_id": str(laptops.id)})
    assert team_of(db, laptops) == nowhere.id and region_codes(db, laptops) == {"APAC"}
    assert entries(db, "settings_updated") == []
    assert len(entries(db, "tracker_team_changed")) == 1


def test_tracker_move_impact_leaves_the_session_clean(db, user_factory, add_member, setup):
    infra, laptops = setup["infra"], setup["laptops"]
    add_member(infra, user_factory(full_name="Infra Lead"), "viewer")
    impact = tracker_move_impact(db, infra, [laptops])
    assert [(c.user.full_name, c.tracker.name, c.after) for c in impact.gains] == [
        ("Infra Lead", "Laptop refresh", "viewer")
    ]
    assert [t.name for t in impact.trackers] == ["Laptop refresh"]
    assert not db.dirty and not db.new and not db.in_nested_transaction()
    assert team_of(db, laptops) == setup["apps"].id and region_codes(db, laptops) == {"APAC"}


def test_move_refused_when_it_raises_own_access(client, db, user_factory, give_set, add_member, region_grant, setup):
    infra, laptops, payroll = setup["infra"], setup["laptops"], setup["payroll"]
    actor = holder(user_factory, give_set, client)
    add_member(infra, actor, "owner")
    response = post(client, moves(infra), {"tracker_id": [str(laptops.id)]}, follow_redirects=True)
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert team_of(db, laptops) == setup["apps"].id and region_codes(db, laptops) == {"APAC"}
    assert entries(db) == []

    # Only the region the tracker gains would reach the actor: still refused.
    other = holder(user_factory, give_set, client)
    region_grant(setup["emea"], other, "viewer")
    response = post(client, moves(infra), {"tracker_id": [str(laptops.id)]}, follow_redirects=True)
    assert SELF_PROMOTION_MESSAGE in text_of(response)
    assert region_codes(db, laptops) == {"APAC"} and team_of(db, laptops) == setup["apps"].id
    assert team_of(db, payroll) is None
    assert entries(db) == []


def test_move_with_a_bad_tracker_id_moves_nothing(client, logged_in_admin, db, tracker_factory, setup):
    infra, laptops = setup["infra"], setup["laptops"]
    gone = tracker_factory(name="Gone")
    gone_id = gone.id
    db.delete(db.get(Tracker, gone_id))
    db.commit()
    for bad in ("abc", "1.5", "9" * 5000, str(MAX_ID + 1), str(gone_id), str(setup["inside"].id)):
        response = client.get(f"{moves(infra)}?tracker_id={laptops.id}&tracker_id={bad}")
        assert response.status_code == 400 and TRACKER_CHOICE_ERROR in text_of(response)
        response = post(client, moves(infra), {"tracker_id": [str(laptops.id), bad]})
        assert response.status_code == 400 and TRACKER_CHOICE_ERROR in text_of(response)
    for empty in ({}, {"tracker_id": ""}):
        response = client.get(moves(infra), query_string=empty)
        assert response.status_code == 400 and CHOOSE_TRACKERS_MESSAGE in text_of(response)
        response = post(client, moves(infra), empty)
        assert response.status_code == 400 and CHOOSE_TRACKERS_MESSAGE in text_of(response)
    assert CHOOSE_TRACKERS_MESSAGE == "Choose at least one tracker."
    assert team_of(db, laptops) == setup["apps"].id and region_codes(db, laptops) == {"APAC"}
    assert entries(db) == []
    # The refusal reopens the picker on the Trackers tab.
    raw = raw_of(client.get(f"{moves(infra)}?tracker_id=abc"))
    assert 'id="tab-trackers"' in raw and 'id="pick-table"' in raw


def test_moves_need_manage_teams_and_a_team(client, logged_in_admin, user_factory, setup):
    infra, laptops = setup["infra"], setup["laptops"]
    assert client.get(f"/admin/teams/99999/trackers?tracker_id={laptops.id}").status_code == 404
    assert post(client, "/admin/teams/99999/trackers", {"tracker_id": str(laptops.id)}).status_code == 404
    sign_in(client, user_factory(full_name="Outsider"))
    assert client.get(f"{moves(infra)}?{query(laptops)}").status_code == 403
    assert post(client, moves(infra), {"tracker_id": str(laptops.id)}).status_code == 403


# --- Row Remove ----------------------------------------------------------------------------------------------------


def test_row_remove_puts_the_tracker_in_no_team_and_returns(client, logged_in_admin, db, setup):
    apps, laptops = setup["apps"], setup["laptops"]
    raw = raw_of(client.get(f"/admin/teams/{apps.id}?tab=trackers"))
    form = re.search(rf'<form [^>]*action="/trackers/{laptops.id}/team".*?</form>', raw, re.S).group(0)
    assert 'name="team_id" value=""' in form and 'name="next" value="team"' in form
    assert f'name="team" value="{apps.id}"' in form
    assert 'data-confirm="Remove Laptop refresh from Applications?' in form
    assert 'title="Remove Laptop refresh from Applications"' in form
    assert "Remove Laptop refresh from Applications</span>" in form

    response = post(client, f"/trackers/{laptops.id}/team", {"team_id": "", "next": "team", "team": str(apps.id)})
    assert response.headers["Location"].endswith(f"/admin/teams/{apps.id}?tab=trackers")
    assert "Moved Laptop refresh to no team." in text_of(client.get(response.headers["Location"]))
    assert team_of(db, laptops) is None and region_codes(db, laptops) == {"APAC"}
    [entry] = entries(db, "tracker_team_changed")
    assert entry.detail == {"before": "Applications", "after": None}

    # An unknown team to return to goes home.
    response = post(client, f"/trackers/{setup['old'].id}/team", {"team_id": "", "next": "team", "team": "abc"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/")
    assert team_of(db, setup["old"]) is None


def gone_after_the_choice(monkeypatch, db, model, row_id):
    """Delete the row from another connection just after the request has read the chosen trackers."""
    real = views.parse_trackers

    def parse(*args):
        found = real(*args)
        db.execute(delete(model).where(model.id == row_id))
        db.commit()
        return found

    monkeypatch.setattr(views, "parse_trackers", parse)


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_tracker_deleted_at_the_same_moment_moves_nothing(client, logged_in_admin, db, monkeypatch, setup, method):
    team, payroll, laptops = setup["infra"], setup["payroll"], setup["laptops"]
    gone_after_the_choice(monkeypatch, db, Tracker, payroll.id)
    if method == "get":
        response = client.get(f"{moves(team)}?{query(payroll, laptops)}")
    else:
        response = post(client, moves(team), {"tracker_id": [str(payroll.id), str(laptops.id)]})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/teams/{team.id}?tab=trackers&add=1")
    assert TRACKERS_CHANGED_MESSAGE in text_of(client.get(response.headers["Location"]))
    db.expire_all()
    assert db.get(Tracker, laptops.id).team_id == setup["apps"].id
    assert entries(db, "tracker_team_changed") == []


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_team_deleted_at_the_same_moment_moves_nothing(
    client, logged_in_admin, db, monkeypatch, team_factory, setup, method
):
    empty = team_factory(name="Empty")
    payroll = setup["payroll"]
    gone_after_the_choice(monkeypatch, db, Team, empty.id)
    if method == "get":
        response = client.get(f"{moves(empty)}?{query(payroll)}")
    else:
        response = post(client, moves(empty), {"tracker_id": str(payroll.id)})
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/teams")
    assert TEAM_DELETED_MESSAGE in text_of(client.get(response.headers["Location"]))
    db.expire_all()
    assert db.get(Tracker, payroll.id).team_id is None


def test_a_region_added_at_the_same_moment_gives_the_tracker_message(client, logged_in_admin, db, monkeypatch, setup):
    """The unique tracker region refuses the move when someone adds the same region in between; the team is fine."""

    def clash(*args):
        raise IntegrityError("INSERT INTO tracker_regions", {}, Exception("duplicate key"))

    monkeypatch.setattr(views, "apply_tracker_moves", clash)
    team, payroll = setup["infra"], setup["payroll"]
    response = post(client, moves(team), {"tracker_id": str(payroll.id)})
    assert response.headers["Location"].endswith(f"/admin/teams/{team.id}?tab=trackers&add=1")
    assert TRACKERS_CHANGED_MESSAGE in text_of(client.get(response.headers["Location"]))
