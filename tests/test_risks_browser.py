"""Risk form section links in a real browser (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in

from tracker.models import Risk

pytestmark = pytest.mark.browser

SUBNAV = "nav[aria-label='Risk sections']"


@pytest.fixture
def editor(page, live_server, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Risks tracker")
    user = user_factory()
    grant(user, tracker, "editor")
    browser_sign_in(page, live_server, user)
    return tracker


def links(page):
    anchors = page.locator(f"{SUBNAV} a")
    return [(a.inner_text(), a.get_attribute("href")) for a in anchors.all()]


def test_new_risk_page_links_to_its_two_sections(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/risks/new")
    assert links(page) == [("Add a risk", "#risk-details"), ("Status and dates", "#risk-status")]
    for _, href in links(page):
        assert page.locator(f"section.settings-section{href}").count() == 1


def test_edit_page_links_to_the_risk_and_its_status(page, live_server, editor, db):
    risk = Risk(tracker_id=editor.id, ref="R1", description="Supplier delay")
    db.add(risk)
    db.commit()
    page.goto(f"{live_server}/trackers/{editor.id}/risks/{risk.id}")
    assert links(page) == [("Risk R1", "#risk-details"), ("Status and dates", "#risk-status")]


def test_register_page_has_no_section_links(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/risks")
    assert page.locator(".subnav").count() == 0


def test_first_section_is_outlined_on_load(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/risks/new")
    assert page.locator(f"{SUBNAV} a[aria-current='location']").all_inner_texts() == ["Add a risk"]
    assert page.evaluate("[...document.querySelectorAll('.settings-section.is-current')].map(s => s.id)") == [
        "risk-details"
    ]


def test_clicked_section_is_underlined_and_outlined(page, live_server, editor):
    page.set_viewport_size({"width": 1000, "height": 700})
    page.goto(f"{live_server}/trackers/{editor.id}/risks/new")
    page.click(f"{SUBNAV} a[href='#risk-status']")
    page.wait_for_timeout(1200)
    assert page.locator(f"{SUBNAV} a[aria-current='location']").all_inner_texts() == ["Status and dates"]
    assert page.evaluate("[...document.querySelectorAll('.settings-section.is-current')].map(s => s.id)") == [
        "risk-status"
    ]
