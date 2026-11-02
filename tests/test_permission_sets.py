"""Permission sets screen: the grid, names, holders and the administrator-only rule (database required)."""

import html

import pytest
from sqlalchemy import delete, select

from tests.conftest import post
from tracker.auth.permissions import PERMISSION_GROUPS, PERMISSIONS, user_permissions
from tracker.models import AuditLog, PermissionSet, PermissionSetHolder, PermissionSetPermission

ENDPOINTS = [
    ("get", "/admin/permission-sets"),
    ("post", "/admin/permission-sets"),
    ("post", "/admin/permission-sets/grid"),
    ("get", "/admin/permission-sets/{id}"),
    ("post", "/admin/permission-sets/{id}/rename"),
    ("post", "/admin/permission-sets/{id}/delete"),
    ("post", "/admin/permission-sets/{id}/holders"),
    ("post", "/admin/permission-sets/{id}/holders/1/delete"),
]


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def entries(db, action: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query))


def stored(db, permission_set) -> list[str]:
    db.expire_all()
    return sorted(
        db.scalars(
            select(PermissionSetPermission.permission).where(PermissionSetPermission.set_id == permission_set.id)
        )
    )


def make_set(db, name: str, permissions: list[str]) -> PermissionSet:
    permission_set = PermissionSet(name=name)
    db.add(permission_set)
    db.flush()
    db.add_all(PermissionSetPermission(set_id=permission_set.id, permission=p) for p in permissions)
    db.commit()
    return permission_set


@pytest.mark.parametrize("method,url", ENDPOINTS)
def test_non_administrators_are_refused_even_with_every_permission(client, logged_in_user, give_set, method, url):
    s = give_set(list(PERMISSIONS), user=logged_in_user)
    target = url.format(id=s.id)
    assert (client.get(target) if method == "get" else post(client, target)).status_code == 403


def test_index_shows_the_grid_for_administrators(client, logged_in_admin, db):
    s = make_set(db, "PMO", ["view_activity"])
    page = text_of(client.get("/admin/permission-sets"))
    assert "Manage users" in page and "Read the Activity screen." in page
    assert f'name="set-{s.id}"' in page and f'name="sets" value="{s.id}"' in page
    assert "PMO" in page


def test_create_set_logs_and_names_are_unique_ignoring_case_and_spaces(client, logged_in_admin, db):
    response = post(client, "/admin/permission-sets", {"name": " PMO ", "description": "Programme office"})
    assert response.status_code == 302
    created = db.scalar(select(PermissionSet).where(PermissionSet.name == "PMO"))
    assert created is not None and created.description == "Programme office"
    [entry] = entries(db, "permission_set_created")
    assert entry.detail == {"name": "PMO"} and entry.entity == "permission_set" and entry.entity_id == str(created.id)
    again = post(client, "/admin/permission-sets", {"name": "  pmo "})
    assert again.status_code == 400 and "A permission set with that name already exists." in text_of(again)
    empty = post(client, "/admin/permission-sets", {"name": "  "})
    assert empty.status_code == 400 and "Enter a permission set name." in text_of(empty)
    assert len(entries(db, "permission_set_created")) == 1


def test_set_name_at_most_100_characters_and_description_at_most_500(client, logged_in_admin, db):
    long_name = post(client, "/admin/permission-sets", {"name": "x" * 101})
    assert long_name.status_code == 400 and "A permission set name can be at most 100 characters." in text_of(long_name)
    long_text = post(client, "/admin/permission-sets", {"name": "Fine", "description": "x" * 501})
    assert long_text.status_code == 400 and "A description can be at most 500 characters." in text_of(long_text)
    assert db.scalar(select(PermissionSet.id)) is None and entries(db) == []


def test_grid_saves_every_set_in_one_action_and_logs_each_changed_set(client, logged_in_admin, db):
    first = make_set(db, "A", ["view_activity"])
    second = make_set(db, "B", ["manage_teams"])
    response = post(
        client,
        "/admin/permission-sets/grid",
        {
            "sets": [str(first.id), str(second.id)],
            f"set-{first.id}": ["create_trackers", "view_activity"],
            f"set-{second.id}": ["manage_teams"],
        },
    )
    assert response.status_code == 302
    assert stored(db, first) == ["create_trackers", "view_activity"] and stored(db, second) == ["manage_teams"]
    [entry] = entries(db, "permission_set_permissions_changed")
    assert entry.entity == "permission_set" and entry.entity_id == str(first.id)
    assert entry.detail["before"] == ["view_activity"]
    assert entry.detail["after"] == ["create_trackers", "view_activity"]


def test_grid_ignores_unknown_permissions_and_sets(client, logged_in_admin, db):
    s = make_set(db, "A", [])
    response = post(
        client,
        "/admin/permission-sets/grid",
        {"sets": [str(s.id), "9999", "abc"], f"set-{s.id}": ["approve"], "set-9999": ["view_activity"]},
    )
    assert response.status_code == 302
    assert stored(db, s) == [] and entries(db) == []
    assert db.scalar(select(PermissionSetPermission.set_id).where(PermissionSetPermission.set_id == 9999)) is None


def test_rename_logs_before_and_after(client, logged_in_admin, db):
    s = make_set(db, "Old", [])
    response = post(client, f"/admin/permission-sets/{s.id}/rename", {"name": "New", "description": "Note"})
    assert response.status_code == 302
    [entry] = entries(db, "permission_set_renamed")
    assert entry.detail == {
        "set": "Old",
        "before": {"name": "Old", "description": ""},
        "after": {"name": "New", "description": "Note"},
    }
    clash = make_set(db, "Other", [])
    refused = post(client, f"/admin/permission-sets/{clash.id}/rename", {"name": "new"})
    assert refused.status_code == 400 and "already exists" in text_of(refused)
    same = post(client, f"/admin/permission-sets/{s.id}/rename", {"name": "NEW", "description": "Note"})
    assert same.status_code == 302


def test_delete_logs_each_holder_then_the_set(client, logged_in_admin, db, user_factory, team_factory, give_set):
    team = team_factory(name="Top")
    sub = team_factory(name="Sub", parent=team)
    person = user_factory()
    s = give_set(["view_activity"], team=sub, name="PMO")
    db.add(PermissionSetHolder(set_id=s.id, user_id=person.id))
    db.commit()
    set_id = s.id
    assert post(client, f"/admin/permission-sets/{set_id}/delete").status_code == 302
    actions = [e.action for e in entries(db)]
    assert actions == ["permission_set_holder_removed", "permission_set_holder_removed", "permission_set_deleted"]
    removed = entries(db, "permission_set_holder_removed")
    assert {"set": "PMO", "team": "Top › Sub"} in [e.detail for e in removed]
    assert [e.target_user_id for e in removed if e.detail == {"set": "PMO"}] == [person.id]
    [deleted] = entries(db, "permission_set_deleted")
    assert deleted.detail == {"name": "PMO", "permissions": ["view_activity"]}
    db.expire_all()
    assert db.scalar(select(PermissionSet.id).where(PermissionSet.id == set_id)) is None
    assert db.scalar(select(PermissionSetHolder.id)) is None
    assert post(client, f"/admin/permission-sets/{set_id}/delete").status_code == 404


def test_add_and_remove_team_and_user_holders_are_logged(client, logged_in_admin, db, user_factory, team_factory):
    team = team_factory(name="Top")
    sub = team_factory(name="Sub", parent=team)
    person = user_factory()
    s = make_set(db, "PMO", ["view_activity"])
    url = f"/admin/permission-sets/{s.id}/holders"
    assert post(client, url, {"holder": f"team:{sub.id}"}).status_code == 302
    assert post(client, url, {"holder": f"user:{person.id}"}).status_code == 302
    added = entries(db, "permission_set_holder_added")
    assert [e.detail for e in added] == [{"set": "PMO", "team": "Top › Sub"}, {"set": "PMO"}]
    assert [e.target_user_id for e in added] == [None, person.id]
    assert all(e.entity == "permission_set" and e.entity_id == str(s.id) for e in added)
    page = text_of(client.get(f"/admin/permission-sets/{s.id}"))
    assert "Top › Sub" in page and person.email in page
    for holder in db.scalars(select(PermissionSetHolder).where(PermissionSetHolder.set_id == s.id)).all():
        assert post(client, f"{url}/{holder.id}/delete").status_code == 302
    removed = entries(db, "permission_set_holder_removed")
    assert [e.detail for e in removed] == [{"set": "PMO", "team": "Top › Sub"}, {"set": "PMO"}]
    assert [e.target_user_id for e in removed] == [None, person.id]


def test_add_holder_refuses_bad_choices(client, logged_in_admin, db, user_factory):
    disabled = user_factory(status="disabled")
    s = make_set(db, "PMO", [])
    url = f"/admin/permission-sets/{s.id}/holders"
    for value in (f"user:{disabled.id}", "team:9999", "user:abc", "nonsense", ""):
        assert post(client, url, {"holder": value}).status_code == 400
    assert entries(db) == [] and db.scalar(select(PermissionSetHolder.id)) is None


def test_duplicate_holder_refused(client, logged_in_admin, db, user_factory, team_factory):
    team, person = team_factory(), user_factory()
    s = make_set(db, "PMO", [])
    url = f"/admin/permission-sets/{s.id}/holders"
    for value in (f"team:{team.id}", f"user:{person.id}"):
        assert post(client, url, {"holder": value}).status_code == 302
        again = post(client, url, {"holder": value})
        assert again.status_code == 400 and "That team or person already holds this set." in text_of(again)
    assert len(entries(db, "permission_set_holder_added")) == 2


def test_removing_a_holder_takes_the_permission_away(client, logged_in_admin, db, user_factory):
    person = user_factory()
    s = make_set(db, "PMO", ["view_activity"])
    assert "view_activity" not in user_permissions(db, person)
    post(client, f"/admin/permission-sets/{s.id}/holders", {"holder": f"user:{person.id}"})
    assert "view_activity" in user_permissions(db, person)
    holder = db.scalar(select(PermissionSetHolder).where(PermissionSetHolder.set_id == s.id))
    post(client, f"/admin/permission-sets/{s.id}/holders/{holder.id}/delete")
    db.expire_all()
    assert "view_activity" not in user_permissions(db, person)


def test_removing_a_holder_of_another_set_is_404(client, logged_in_admin, db, user_factory):
    person = user_factory()
    one, two = make_set(db, "One", []), make_set(db, "Two", [])
    holder = PermissionSetHolder(set_id=two.id, user_id=person.id)
    db.add(holder)
    db.commit()
    assert post(client, f"/admin/permission-sets/{one.id}/holders/{holder.id}/delete").status_code == 404
    assert db.get(PermissionSetHolder, holder.id) is not None


def test_a_very_long_holder_id_is_400_not_500(client, logged_in_admin, db):
    s = make_set(db, "PMO", [])
    url = f"/admin/permission-sets/{s.id}/holders"
    for value in ("team:" + "9" * 5000, "user:" + "9" * 5000, f"user:{2**31}"):
        assert post(client, url, {"holder": value}).status_code == 400
    grid = post(client, "/admin/permission-sets/grid", {"sets": ["9" * 5000], "set-1": ["view_activity"]})
    assert grid.status_code == 302 and entries(db) == []


def test_removing_a_holder_removed_at_the_same_moment(client, logged_in_admin, db, team_factory, monkeypatch):
    from tracker.permsets import views as permset_views

    team = team_factory(name="Network")
    s = make_set(db, "PMO", [])
    holder = PermissionSetHolder(set_id=s.id, team_id=team.id)
    db.add(holder)
    db.commit()
    original = permset_views.load_team_rows

    def remove_first(session, lock=False):
        db.execute(delete(PermissionSetHolder).where(PermissionSetHolder.id == holder.id))
        db.commit()
        return original(session, lock)

    monkeypatch.setattr(permset_views, "load_team_rows", remove_first)
    url = f"/admin/permission-sets/{s.id}/holders/{holder.id}/delete"
    response = post(client, url, follow_redirects=True)
    assert response.status_code == 200 and "That holder of PMO has already been removed." in text_of(response)
    assert entries(db) == []


def test_permission_sets_screen_warns_about_users_and_teams_together(client, logged_in_admin):
    page = text_of(client.get("/admin/permission-sets"))
    assert "Holding both Manage users and Manage teams gives reach close to an administrator's" in page


# --- The cards ------------------------------------------------------------------------------------------------------


def cards(page: str) -> list[str]:
    return page.split("data-set-card")[1:]


def test_permission_groups_cover_every_permission_once():
    assert [name for name, _ in PERMISSION_GROUPS] == ["People and teams", "Trackers", "Application"]
    grouped = [p for _, keys in PERMISSION_GROUPS for p in keys]
    assert sorted(grouped) == sorted(PERMISSIONS) and len(grouped) == len(set(grouped))


def test_index_shows_the_locked_administrators_card_then_a_card_per_set(client, logged_in_admin, db):
    pmo = make_set(db, "PMO", ["view_activity"])
    make_set(db, "Auditors", [])
    page = text_of(client.get("/admin/permission-sets"))
    assert page.index("Administrators") < page.index("Auditors") < page.index("PMO")
    assert "Built in" in page and "7/7" in page and "Every permission, always." in page
    assert "1/7" in page and "0/7" in page and "No description." in page
    assert 'aria-label="View activity for PMO"' in page and f'name="set-{pmo.id}"' in page
    assert "People and teams" in page and "Application" in page
    assert len(cards(page)) == 2 and "data-permission-cards" in page
    assert "Saving applies every card at once." in page


def test_cards_count_holders(client, logged_in_admin, db, user_factory, team_factory, give_set):
    both = give_set(["view_activity"], team=team_factory(name="Ops"), name="Both")
    give_set(["view_activity"], user=user_factory(), name="Solo")
    db.add(PermissionSetHolder(set_id=both.id, user_id=user_factory().id))
    db.add(PermissionSetHolder(set_id=both.id, user_id=user_factory().id))
    db.commit()
    make_set(db, "Empty", [])
    user_factory(is_admin=True)
    user_factory(is_admin=True, status="disabled")
    page = text_of(client.get("/admin/permission-sets"))
    assert "Held by 1 team and 2 people" in page and "Held by 1 person" in page
    assert "Nobody holds this set yet." in page
    assert "Held by 2 people" in page  # the signed-in administrator and one more active one


def test_card_warns_only_where_a_set_grants_users_and_teams(client, logged_in_admin, db):
    make_set(db, "Both", ["manage_users", "manage_teams"])
    make_set(db, "One", ["manage_users"])
    page = text_of(client.get("/admin/permission-sets"))
    warning = "Holding both Manage users and Manage teams gives reach close to an administrator's."
    both, one = cards(page)
    assert warning in both and warning not in one


def test_no_sets_still_shows_administrators_and_new_set_cards(client, logged_in_admin):
    page = text_of(client.get("/admin/permission-sets"))
    assert "Administrators" in page and 'id="new-set"' in page and 'href="#new-set"' in page
    assert "Save permissions" not in page


def test_failed_create_keeps_the_typed_name_in_the_new_set_card(client, logged_in_admin, db):
    make_set(db, "PMO", [])
    response = post(client, "/admin/permission-sets", {"name": "pmo", "description": "Again"})
    page = text_of(response)
    assert response.status_code == 400 and 'id="new-set"' in page and 'value="pmo"' in page
    assert len(cards(page)) == 1


def test_set_page_links_to_its_card(client, logged_in_admin, db):
    s = make_set(db, "PMO", [])
    page = text_of(client.get(f"/admin/permission-sets/{s.id}"))
    assert f"/admin/permission-sets#card-{s.id}" in page and "#grid" not in page


def test_tick_boxes_are_described_by_the_permission_help(client, logged_in_admin, db):
    s = make_set(db, "PMO", [])
    page = text_of(client.get("/admin/permission-sets"))
    assert f'aria-describedby="help-{s.id}-view_activity"' in page
    assert f'id="help-{s.id}-view_activity"' in page
