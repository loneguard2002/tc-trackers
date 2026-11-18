"""Permission sets screen: the grid, names, holders and the administrator-only rule (database required)."""

import html

import pytest
from sqlalchemy import delete, func, select

from tests.conftest import post
from tracker.auth.permissions import PERMISSION_GROUPS, PERMISSIONS, user_permissions
from tracker.models import AuditLog, PermissionSet, PermissionSetHolder, PermissionSetPermission

ENDPOINTS = [
    ("get", "/admin/permission-sets"),
    ("post", "/admin/permission-sets"),
    ("post", "/admin/permission-sets/grid"),
    ("get", "/admin/permission-sets/new"),
    ("get", "/admin/permission-sets/{id}"),
    ("get", "/admin/permission-sets/{id}/panel"),
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
    assert {"set": "PMO", "team": "Sub"} in [e.detail for e in removed]
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
    assert [e.detail for e in added] == [{"set": "PMO", "team": "Sub"}, {"set": "PMO"}]
    assert [e.target_user_id for e in added] == [None, person.id]
    assert all(e.entity == "permission_set" and e.entity_id == str(s.id) for e in added)
    page = text_of(client.get(f"/admin/permission-sets/{s.id}"))
    assert '<span class="cell-title">Sub</span>' in page and person.email in page
    for holder in db.scalars(select(PermissionSetHolder).where(PermissionSetHolder.set_id == s.id)).all():
        assert post(client, f"{url}/{holder.id}/delete").status_code == 302
    removed = entries(db, "permission_set_holder_removed")
    assert [e.detail for e in removed] == [{"set": "PMO", "team": "Sub"}, {"set": "PMO"}]
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
    assert (
        "Manage users and Manage teams together give almost administrator-level access, so give that pair with care."
        in page
    )


# --- The cards ------------------------------------------------------------------------------------------------------


def cards(page: str) -> list[str]:
    return page.split("data-set-card")[1:]


def test_permission_groups_cover_every_permission_once():
    assert [name for name, _ in PERMISSION_GROUPS] == ["People and teams", "Lists", "Trackers", "Application"]
    grouped = [p for _, keys in PERMISSION_GROUPS for p in keys]
    assert sorted(grouped) == sorted(PERMISSIONS) and len(grouped) == len(set(grouped))


def test_index_shows_the_locked_administrators_card_then_a_card_per_set(client, logged_in_admin, db):
    pmo = make_set(db, "PMO", ["view_activity"])
    make_set(db, "Auditors", [])
    page = text_of(client.get("/admin/permission-sets"))
    assert page.index("Administrators") < page.index("Auditors") < page.index("PMO")
    assert "Built in" in page and "8/8" not in page and "Every permission, always." in page
    assert "1/8" not in page and "No description." in page
    assert 'aria-label="View activity for PMO"' in page and f'name="set-{pmo.id}"' in page
    assert "People and teams" in page and "Lists" in page and "Application" in page
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


def test_no_sets_still_shows_administrators_and_links_to_the_create_page(client, logged_in_admin):
    page = text_of(client.get("/admin/permission-sets"))
    assert "Administrators" in page and 'id="new-set"' not in page and 'href="/admin/permission-sets/new"' in page


def test_failed_create_keeps_the_typed_name_on_the_create_page(client, logged_in_admin, db):
    make_set(db, "PMO", [])
    response = post(client, "/admin/permission-sets", {"name": "pmo", "description": "Again"})
    page = text_of(response)
    assert response.status_code == 400 and 'value="pmo"' in page and "already" in page.lower()


def test_set_page_links_to_its_card(client, logged_in_admin, db):
    s = make_set(db, "PMO", [])
    page = text_of(client.get(f"/admin/permission-sets/{s.id}"))
    assert f"/admin/permission-sets#card-{s.id}" in page and "#grid" not in page


def test_tick_boxes_are_described_by_the_permission_help(client, logged_in_admin, db):
    s = make_set(db, "PMO", [])
    page = text_of(client.get("/admin/permission-sets"))
    assert f'aria-describedby="help-{s.id}-view_activity"' in page
    assert f'id="help-{s.id}-view_activity"' in page


# --- The redesigned page: create with permissions and holders, return to the page, /new and the panel -----------------


def test_create_saves_permissions_and_holders_and_logs_each(client, logged_in_admin, db, user_factory, team_factory):
    team, person = team_factory(name="Top"), user_factory()
    other = [name for name in PERMISSIONS if name != "view_activity"][0]
    response = post(
        client,
        "/admin/permission-sets",
        {
            "name": "PMO",
            "permissions": ["view_activity", other],
            "holders": [f"team:{team.id}", f"user:{person.id}"],
        },
    )
    assert response.status_code == 302
    created = db.scalar(select(PermissionSet).where(PermissionSet.name == "PMO"))
    assert stored(db, created) == sorted(["view_activity", other])
    assert len(db.scalars(select(PermissionSetHolder).where(PermissionSetHolder.set_id == created.id)).all()) == 2
    assert len(entries(db, "permission_set_created")) == 1
    [changed] = entries(db, "permission_set_permissions_changed")
    assert changed.entity_id == str(created.id) and changed.detail["set"] == "PMO"
    added = entries(db, "permission_set_holder_added")
    assert [e.target_user_id for e in added] == [None, person.id]


def test_create_without_permissions_writes_no_permissions_entry(client, logged_in_admin, db):
    post(client, "/admin/permission-sets", {"name": "Empty"})
    assert entries(db, "permission_set_permissions_changed") == []


def test_create_ignores_bad_permissions_and_holders(client, logged_in_admin, db, user_factory, team_factory):
    team, person, gone = team_factory(), user_factory(), user_factory(status="disabled")
    response = post(
        client,
        "/admin/permission-sets",
        {
            "name": "PMO",
            "permissions": ["not_a_permission"],
            "holders": [
                f"team:{team.id}",
                f"team:{team.id}",
                f"user:{person.id}",
                f"user:{gone.id}",
                "team:9999",
                "user:abc",
                "nonsense",
                "",
            ],
        },
    )
    assert response.status_code == 302
    created = db.scalar(select(PermissionSet).where(PermissionSet.name == "PMO"))
    assert stored(db, created) == []
    assert entries(db, "permission_set_permissions_changed") == []
    assert len(db.scalars(select(PermissionSetHolder).where(PermissionSetHolder.set_id == created.id)).all()) == 2
    assert len(entries(db, "permission_set_holder_added")) == 2


def test_create_return_to_index_redirects_to_the_page_with_the_set(client, logged_in_admin, db):
    response = post(client, "/admin/permission-sets", {"name": "PMO", "return_to": "index"})
    created = db.scalar(select(PermissionSet).where(PermissionSet.name == "PMO"))
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/permission-sets?set={created.id}")
    other = post(client, "/admin/permission-sets", {"name": "Two", "return_to": "elsewhere"})
    second = db.scalar(select(PermissionSet).where(PermissionSet.name == "Two"))
    assert other.headers["Location"].endswith(f"/admin/permission-sets/{second.id}")


def test_create_with_a_taken_name_and_return_to_index_shows_the_new_page_with_values(client, logged_in_admin, db):
    make_set(db, "PMO", [])
    response = post(
        client,
        "/admin/permission-sets",
        {"name": " pmo ", "description": "Kept note", "permissions": ["view_activity"], "return_to": "index"},
    )
    page = text_of(response)
    assert response.status_code == 400
    assert "A permission set with that name already exists." in page
    assert 'value=" pmo "' in page or 'value="pmo"' in page
    assert "Kept note" in page
    assert db.scalar(select(func.count()).select_from(PermissionSet)) == 1


def test_new_page_renders_the_form(client, logged_in_admin):
    response = client.get("/admin/permission-sets/new")
    page = text_of(response)
    assert response.status_code == 200
    assert 'name="name"' in page and 'name="description"' in page and "Create" in page
    assert 'name="return_to" value="index"' in page


def test_index_passes_team_choices_and_people(client, logged_in_admin, db, user_factory, team_factory):
    team = team_factory(name="Desk")
    person = user_factory(full_name="Zed Active", email="zed@example.com")
    user_factory(full_name="Gone Person", status="disabled")
    page = text_of(client.get("/admin/permission-sets"))
    assert str(team.id) is not None and page  # renders
    from tracker.permsets import views

    seen = {}
    original = views.render_template

    def spy(name, **context):
        seen.update(context)
        return original(name, **context)

    views.render_template = spy
    try:
        client.get("/admin/permission-sets")
    finally:
        views.render_template = original
    assert (team.id, "Desk") in [tuple(c) for c in seen["team_choices"]]
    assert (person.id, "Zed Active", "zed@example.com") in [tuple(p) for p in seen["people"]]
    assert "Gone Person" not in [p[1] for p in seen["people"]]


def test_panel_lists_holders_with_remove_forms_and_permissions(client, logged_in_admin, db, user_factory, team_factory):
    team, person, free = team_factory(name="Top"), user_factory(), user_factory(full_name="Free Person")
    s = make_set(db, "PMO", ["view_activity"])
    for value in (f"team:{team.id}", f"user:{person.id}"):
        post(client, f"/admin/permission-sets/{s.id}/holders", {"holder": value})
    response = client.get(f"/admin/permission-sets/{s.id}/panel")
    page = text_of(response)
    assert response.status_code == 200
    assert "<html" not in page and f'data-panel-set="{s.id}"' in page
    assert "Top" in page and person.email in page and "Read the Activity screen." not in page
    assert "Free Person" in page and f'value="user:{free.id}"' in page
    holders = db.scalars(select(PermissionSetHolder).where(PermissionSetHolder.set_id == s.id)).all()
    for h in holders:
        assert f"/admin/permission-sets/{s.id}/holders/{h.id}/delete" in page
    assert page.count('name="return_to" value="index"') == len(holders) + 1
    assert page.count('name="csrf_token"') == len(holders) + 1
    assert f'value="team:{team.id}"' not in page


def test_panel_404s_for_an_unknown_set(client, logged_in_admin):
    assert client.get("/admin/permission-sets/9999/panel").status_code == 404


def test_rename_add_and_remove_with_return_to_index_redirect_to_the_set(client, logged_in_admin, db, team_factory):
    team = team_factory()
    s = make_set(db, "PMO", [])
    base = f"/admin/permission-sets/{s.id}"
    target = f"/admin/permission-sets?set={s.id}"
    renamed = post(client, f"{base}/rename", {"name": "PMO2", "return_to": "index"})
    assert renamed.status_code == 302 and renamed.headers["Location"].endswith(target)
    unchanged = post(client, f"{base}/rename", {"name": "PMO2", "return_to": "index"})
    assert unchanged.headers["Location"].endswith(target)
    added = post(client, f"{base}/holders", {"holder": f"team:{team.id}", "return_to": "index"})
    assert added.status_code == 302 and added.headers["Location"].endswith(target)
    holder = db.scalar(select(PermissionSetHolder).where(PermissionSetHolder.set_id == s.id))
    removed = post(client, f"{base}/holders/{holder.id}/delete", {"return_to": "index"})
    assert removed.status_code == 302 and removed.headers["Location"].endswith(target)
    plain = post(client, f"{base}/holders", {"holder": f"team:{team.id}"})
    assert plain.headers["Location"].endswith(base)
    deleted = post(client, f"{base}/delete", {"return_to": "index"})
    assert deleted.headers["Location"].endswith("/admin/permission-sets")
