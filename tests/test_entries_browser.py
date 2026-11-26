"""The Entries page in a real browser: search, a heading sort and paging by weeks (database)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.models import CompletionEntry, Group

pytestmark = pytest.mark.browser


def _seed(db, tracker_factory, user_factory, grant, weeks: int = 12):
    tracker = tracker_factory(first_week_ending=date(2026, 1, 2), last_week_ending=date(2026, 12, 25))
    user = user_factory()
    grant(user, tracker, "editor")
    group = Group(tracker_id=tracker.id, name="Kestrel site", baseline=10)
    db.add(group)
    db.commit()
    for n in range(weeks):
        ending = date(2026, 1, 2) + timedelta(weeks=n)
        for k in range(3):
            db.add(
                CompletionEntry(
                    tracker_id=tracker.id,
                    group_id=group.id,
                    entry_date=ending - timedelta(days=k),
                    week_ending=ending,
                    quantity=k + 1,
                    note="special" if (n, k) == (4, 0) else f"note-{n}-{k}",
                )
            )
    db.commit()
    return tracker, user


def _open(page, live_server, user, tracker):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user)
    page.goto(f"{live_server}/trackers/{tracker.id}/entries")


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_search_sort_and_page_2_work_without_errors(page, live_server, db, tracker_factory, user_factory, grant):
    tracker, user = _seed(db, tracker_factory, user_factory, grant)
    _open(page, live_server, user, tracker)
    expect(page.locator(".week-block")).to_have_count(10)
    expect(page.locator(".pager-count")).to_have_text("Showing weeks 1–10 of 12 · 36 entries")
    page.click(".pager-pages a[aria-label='Page 2']")
    page.wait_for_url("**page=2**")
    expect(page.locator(".week-block")).to_have_count(2)
    expect(page.locator(".pager-count")).to_have_text("Showing weeks 11–12 of 12 · 36 entries")
    page.click(".week-block .entry-table th a.sort-button:has-text('Quantity') >> nth=0")
    page.wait_for_url("**sort=quantity**")
    assert "page=" not in page.url  # a sort returns to page 1
    assert page.locator(".entry-table th", has_text="Quantity").first.get_attribute("aria-sort") == "ascending"
    page.fill("#entry-q", "special")
    page.press("#entry-q", "Enter")
    page.wait_for_url("**q=special**")
    assert "sort=quantity" in page.url
    expect(page.locator(".week-block")).to_have_count(1)
    expect(page.locator(".entry-table tbody tr")).to_have_count(1)
    expect(page.locator(".pager-count")).to_have_text("Showing 1 of 12 weeks · 1 entry")
    _clean(page)


def test_on_a_phone_nothing_scrolls_sideways(page, live_server, db, tracker_factory, user_factory, grant):
    tracker, user = _seed(db, tracker_factory, user_factory, grant)
    page.set_viewport_size({"width": 390, "height": 900})
    _open(page, live_server, user, tracker)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator(".entry-table td[data-label='Quantity']").first).to_be_attached()
    _clean(page)


def test_a_week_heading_stays_at_the_top_while_a_long_week_scrolls(
    page, live_server, db, tracker_factory, user_factory, grant
):
    tracker, user = _seed(db, tracker_factory, user_factory, grant, weeks=1)
    group = db.query(Group).filter_by(tracker_id=tracker.id).one()
    ending = date(2026, 1, 2)
    for n in range(80):
        db.add(
            CompletionEntry(
                tracker_id=tracker.id,
                group_id=group.id,
                entry_date=ending,
                week_ending=ending,
                quantity=1,
                note=f"long-{n}",
            )
        )
    db.commit()
    page.set_viewport_size({"width": 1280, "height": 700})
    _open(page, live_server, user, tracker)
    heading = page.locator(".week-block[open] .entry-table thead th").first
    expect(heading).to_be_visible()
    assert heading.evaluate("el => getComputedStyle(el).position") == "sticky"
    page.evaluate("document.querySelector('.entry-table tbody tr:nth-child(40)').scrollIntoView({block: 'center'})")
    top = heading.evaluate("el => el.getBoundingClientRect().top")
    topbar = page.evaluate("document.querySelector('.topbar, header').getBoundingClientRect().height")
    assert 0 <= top <= topbar + 80, top  # pinned under the top bar, not scrolled out of view
    _clean(page)
