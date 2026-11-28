"""Create teams is its own permission (the owner, 28 Nov 2026): Manage teams opens the Teams pages, and creating a team
needs Create teams too (database)."""

from __future__ import annotations

import pytest
from conftest import post
from sqlalchemy import select

from tracker.models import Team


@pytest.fixture
def lead(logged_in_user, give_set):
    give_set(["manage_teams"], user=logged_in_user)
    return logged_in_user


def test_manage_teams_alone_cannot_create_a_team(client, db, lead, region_factory):
    region = region_factory("EMEA")
    assert post(client, "/admin/teams", {"name": "New desk", "region_id": str(region.id)}).status_code == 403
    assert db.scalars(select(Team)).all() == []


def test_create_teams_creates_a_team(client, db, lead, give_set, region_factory):
    give_set(["create_teams"], user=lead)
    region = region_factory("EMEA")
    assert post(client, "/admin/teams", {"name": "New desk", "region_id": str(region.id)}).status_code == 302
    assert [team.name for team in db.scalars(select(Team))] == ["New desk"]


@pytest.mark.parametrize("view", ["new", "classic"])
def test_new_team_is_offered_only_with_create_teams(client, lead, give_set, team_factory, view):
    team = team_factory("Desk")
    for url in ("/admin/teams", f"/admin/teams/{team.id}", f"/admin/teams/{team.id}?tab=below"):
        html = client.get(f"{url}{'&' if '?' in url else '?'}view={view}", follow_redirects=True).get_data(as_text=True)
        assert "New team" not in html and 'action="/admin/teams"' not in html, url
    give_set(["create_teams"], user=lead)
    html = client.get(f"/admin/teams?view={view}", follow_redirects=True).get_data(as_text=True)
    assert 'action="/admin/teams"' in html
