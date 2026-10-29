"""Entries, Risks and the risk form in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.engine.weeks import week_ending_for
from tracker.models import CompletionEntry, Group, Risk

pytestmark = pytest.mark.browser

# Weeks around today, so the quick-add date (today) falls inside the tracker.
FIRST = week_ending_for(date.today() - timedelta(days=21), 4)
LAST = FIRST + timedelta(weeks=7)


@pytest.fixture
def seeded(db, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Register tracker", first_week_ending=FIRST, last_week_ending=LAST)
    ld5 = Group(tracker_id=tracker.id, name="LD5", baseline=100, sort_order=1)
    ld6 = Group(tracker_id=tracker.id, name="<i>LD6</i>", baseline=50, sort_order=2)
    db.add_all([ld5, ld6])
    db.flush()
    for group, quantity, week, note in ((ld5, 5, FIRST, "alpha"), (ld6, 9, FIRST + timedelta(weeks=1), "gamma")):
        db.add(
            CompletionEntry(
                tracker_id=tracker.id,
                group_id=group.id,
                quantity=quantity,
                entry_date=week - timedelta(days=1),
                week_ending=week,
                note=note,
            )
        )
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="Supplier delay", status="Open", rag="Red"))
    db.add(
        Risk(
            tracker_id=tracker.id,
            ref="R2",
            description="Weekend access",
            owner_role="Facilities",
            status="Open",
            rag="Amber",
            target_date=date.today() - timedelta(days=3),
        )
    )
    db.add(Risk(tracker_id=tracker.id, ref="R3", description="Old issue", status="Closed", rag="Green"))
    db.commit()
    editor = user_factory()
    grant(editor, tracker, "editor")
    return SimpleNamespace(tracker=tracker, editor=editor, ld5=ld5)


def open_page(page, base_url, seeded, path):
    page.add_init_script(RECORDER)
    browser_sign_in(page, base_url, seeded.editor)
    page.goto(f"{base_url}/trackers/{seeded.tracker.id}/{path}")


def assert_clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_quick_add_names_the_week_and_records(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    hint = page.locator("[data-week-hint]")
    expect(hint).to_contain_text("Counts towards week ending")
    page.fill("#qa-date", (LAST + timedelta(days=3)).isoformat())
    expect(hint).to_have_text("Outside this tracker's weeks")
    page.fill("#qa-date", date.today().isoformat())
    page.select_option("#qa-group", label="LD5")
    page.fill("#qa-quantity", "4")
    page.get_by_role("button", name="Record").click()
    expect(page.get_by_text("Recorded 4 for LD5")).to_be_visible()
    assert page.url.endswith(f"/trackers/{seeded.tracker.id}/entries")
    assert_clean(page)


def test_markup_in_names_is_shown_as_text(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    expect(page.locator(".entry-table td:nth-child(2)", has_text="<i>LD6</i>")).to_have_count(1)
    expect(page.locator(".chip", has_text="<i>LD6</i>")).to_have_count(1)
    assert page.locator(".entries-page i").count() == 0


def test_delete_asks_in_the_row(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    row = page.locator(".entry-table tr", has_text="gamma")
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    row.get_by_role("button", name="Delete 9").click()
    expect(row.get_by_text("Delete 9 for <i>LD6</i>?")).to_be_visible()
    row.get_by_role("button", name="Keep").click()
    expect(row.locator("[data-confirm-box]")).to_be_hidden()
    row.get_by_role("button", name="Delete 9").click()
    row.locator("[data-confirm-yes]").click()
    expect(page.get_by_text("Entry deleted.")).to_be_visible()
    expect(page.locator(".entry-table tr", has_text="gamma")).to_have_count(0)
    assert dialogs == []  # the in-row question replaces the browser dialog
    assert_clean(page)


def test_week_choice_submits_by_itself(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    expect(page.locator("[data-autosubmit-fallback]")).to_be_hidden()
    page.select_option("#week", FIRST.isoformat())
    page.wait_for_url(f"**week={FIRST.isoformat()}")
    expect(page.locator(".entry-table tr", has_text="alpha")).to_have_count(1)
    expect(page.locator(".entry-table tr", has_text="gamma")).to_have_count(0)


def test_risk_chips_and_search_filter_the_register(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    rows = page.locator("[data-risk-rows] tr:visible")
    expect(rows).to_have_count(2)
    page.get_by_role("button", name="Past target date").click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Weekend access")
    page.get_by_role("button", name="All open").click()
    page.get_by_placeholder("Search risks").fill("supplier")
    expect(rows).to_have_count(1)
    page.get_by_placeholder("Search risks").fill("nothing like this")
    expect(page.get_by_text("No risks match this filter.")).to_be_visible()
    expect(page.locator(".closed-block summary")).to_have_text("Closed risks (1)")
    assert_clean(page)


def test_risk_delete_asks_first(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    messages = []

    def answer(dialog, accept):
        messages.append(dialog.message)
        dialog.accept() if accept else dialog.dismiss()

    page.once("dialog", lambda dialog: answer(dialog, False))
    page.get_by_role("button", name="Delete risk R1").click()
    expect(page.locator("[data-risk-rows] tr")).to_have_count(2)
    page.once("dialog", lambda dialog: answer(dialog, True))
    page.get_by_role("button", name="Delete risk R1").click()
    expect(page.get_by_text("Risk R1 deleted.")).to_be_visible()
    assert messages[0].startswith("Delete risk R1?")
    assert_clean(page)


def test_risk_form_preview_follows_the_fields(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks/new")
    preview = page.locator("[data-preview]")
    expect(preview.locator("[data-preview-ref]")).to_have_text("R4")
    page.fill("#description", "Stock held at customs")
    page.fill("#owner_role", "Regional lead")
    page.select_option("#group_id", label="LD5")
    page.fill("#target_date", "2026-11-13")
    page.locator(".segmented label", has_text="Red").click()
    expect(preview).to_have_class("top-risk top-risk-red")
    expect(preview.locator("[data-preview-desc]")).to_have_text("Stock held at customs")
    expect(preview.locator("[data-preview-meta]")).to_have_text("Regional lead · LD5 · Open · target 13 Nov 2026")
    page.locator(".segmented label", has_text="Closed").click()
    expect(page.get_by_text("Closed risks do not appear on the report.")).to_be_visible()
    expect(page.locator("[data-preview-open]")).to_be_hidden()
    assert_clean(page)


def test_locations_page_raises_no_policy_errors(page, live_server, seeded):
    open_page(page, live_server, seeded, "groups")
    expect(page.locator(".group-table tbody tr")).to_have_count(2)
    expect(page.locator(".group-total")).to_contain_text("All locations")
    assert_clean(page)
