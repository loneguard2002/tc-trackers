"""Database-free template checks: the content security policy and role-dependent navigation."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import g, render_template

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


def render_nav(app, role: str) -> str:
    tracker = SimpleNamespace(id=7, group_label="Site", status="active")
    with app.test_request_context("/"):
        g.role = role
        return render_template("trackers/_nav.html", tracker=tracker)


def test_groups_link_hidden_from_viewers(app):
    assert "/trackers/7/groups" not in render_nav(app, "viewer")


@pytest.mark.parametrize("role", ["editor", "owner"])
def test_groups_link_shown_to_editors_and_owners(app, role):
    assert "/trackers/7/groups" in render_nav(app, role)
