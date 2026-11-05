"""Database-free template checks: the content security policy and role-dependent navigation."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import g, render_template

from tracker.auth.permissions import PERMISSIONS

TEMPLATES = Path(__file__).resolve().parent.parent / "tracker" / "templates"
# Rendered outside the browser's CSP: an email (inline styles are required) and the standalone PDF/PNG document.
EXEMPT = {Path("mail/email_body.html"), Path("report/print.html")}
FORBIDDEN = {
    "style attribute": re.compile(r"<[^>]*\sstyle\s*=", re.IGNORECASE),
    "style block": re.compile(r"<style\b", re.IGNORECASE),
    "inline script": re.compile(r"<script\b(?![^>]*\bsrc\s*=)", re.IGNORECASE),
    "inline event handler": re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE),
}


def served_templates() -> list[Path]:
    return sorted(p for p in TEMPLATES.rglob("*.html") if p.relative_to(TEMPLATES) not in EXEMPT)


def test_templates_found():
    assert len(served_templates()) > 15


@pytest.mark.parametrize("path", served_templates(), ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_template_has_nothing_the_csp_blocks(path):
    source = path.read_text(encoding="utf-8")
    problems = [name for name, pattern in FORBIDDEN.items() if pattern.search(source)]
    assert not problems, f"{path.relative_to(TEMPLATES)} contains: {', '.join(problems)}"


def render_nav(app, role: str | None, held: frozenset[str] = frozenset()) -> str:
    tracker = SimpleNamespace(id=7, group_label="Site", status="active")
    with app.test_request_context("/"):
        g.role = role
        return render_template(
            "trackers/_nav.html", tracker=tracker, current_user=None, can=lambda permission: permission in held
        )


def test_a_team_manager_without_a_role_sees_only_the_access_tab(app):
    nav = render_nav(app, None, frozenset({"manage_teams"}))
    assert nav.count('<a class="tab') == 1 and "/trackers/7/roles" in nav
    assert "/trackers/7/report" not in nav


def test_access_tab_hidden_without_manage_teams(app):
    assert "/trackers/7/roles" not in render_nav(app, "owner")


def test_groups_link_hidden_from_viewers(app):
    assert "/trackers/7/groups" not in render_nav(app, "viewer")


@pytest.mark.parametrize("role", ["editor", "owner"])
def test_groups_link_shown_to_editors_and_owners(app, role):
    assert "/trackers/7/groups" in render_nav(app, role)


def render_sidebar(app, is_admin: bool, held: set[str]) -> str:
    user = SimpleNamespace(id=1, full_name="Pat", is_admin=is_admin)
    with app.test_request_context("/"):
        return render_template("base.html", current_user=user, can=lambda p: is_admin or p in held)


# Permission -> sidebar link. Tasks 5, 9 and 11 add a row each; nothing else in the tests below changes.
LINKS = {
    "manage_users": 'href="/admin/users"',
    "manage_teams": 'href="/admin/teams"',
    "import_workbooks": 'href="/import"',
    "manage_email_settings": 'href="/admin/smtp"',
    "view_activity": 'href="/admin/activity"',
}


@pytest.mark.parametrize(
    "held",
    [
        set(),
        {"import_workbooks"},
        {"manage_email_settings"},
        {"import_workbooks", "manage_email_settings"},
        {"view_all_trackers"},
        {"manage_teams"},
        {"manage_users"},
        {"view_activity"},
    ],
)
def test_sidebar_shows_only_the_links_held(app, held):
    html = render_sidebar(app, is_admin=False, held=held)
    for permission, link in LINKS.items():
        assert (link in html) == (permission in held)
    assert ("Administration" in html) == bool(held & (set(LINKS) - {"import_workbooks"}))


def test_import_link_sits_under_trackers_not_administration(app):
    html = render_sidebar(app, is_admin=True, held=set())
    assert html.index('href="/"') < html.index('href="/import"') < html.index("Administration")


def test_sidebar_shows_every_link_to_administrators(app):
    html = render_sidebar(app, is_admin=True, held=set())
    assert 'href="/admin/users"' in html
    assert all(link in html for link in LINKS.values())


@pytest.mark.parametrize("held", [set(), {"manage_teams"}, {"import_workbooks"}, set(PERMISSIONS)])
def test_permission_sets_link_only_for_administrators(app, held):
    assert 'href="/admin/permission-sets"' not in render_sidebar(app, is_admin=False, held=held)
    assert 'href="/admin/permission-sets"' in render_sidebar(app, is_admin=True, held=set())
