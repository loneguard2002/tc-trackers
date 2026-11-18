"""Entries, Risks and the risk form in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from sqlalchemy import select
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
    page.fill("#qa-date", (FIRST - timedelta(days=10)).isoformat())
    expect(hint).to_have_text("Outside this tracker's weeks")
    page.fill("#qa-date", (date.today() + timedelta(days=1)).isoformat())
    expect(hint).to_have_text("The date cannot be after today")
    day = (date.today() - timedelta(days=1)).isoformat()
    page.fill("#qa-date", day)
    page.select_option("#qa-group", label="LD5")
    page.fill("#qa-quantity", "4")
    page.fill("#qa-note", "first")
    page.get_by_role("button", name="Record").click()
    expect(page.get_by_text("Recorded 4 for LD5")).to_be_visible()
    assert page.url.endswith(f"/trackers/{seeded.tracker.id}/entries")
    # Ready for the next entry: same location and date, empty quantity and note, the cursor in Quantity.
    expect(page.locator("#qa-group option:checked")).to_have_text("LD5")
    expect(page.locator("#qa-date")).to_have_value(day)
    expect(page.locator("#qa-quantity")).to_have_value("")
    expect(page.locator("#qa-note")).to_have_value("")
    expect(page.locator("#qa-quantity")).to_be_focused()
    expect(page.locator(".entry-table tr.is-new", has_text="first")).to_have_count(1)
    page.keyboard.type("6")
    page.keyboard.press("Enter")
    expect(page.get_by_text("Recorded 6 for LD5")).to_be_visible()
    assert_clean(page)


def test_entry_rows_are_one_line_and_cards_on_a_phone(page, live_server, seeded, db):
    entry = db.scalars(select(CompletionEntry).where(CompletionEntry.note == "alpha")).one()
    entry.note = "Late delivery from the supplier, floor three"
    db.commit()
    page.set_viewport_size({"width": 1280, "height": 900})
    open_page(page, live_server, seeded, "entries")
    row = page.locator(".entry-table tr", has_text="Late delivery")
    edit, delete = row.locator("a.tool-button").bounding_box(), row.locator("button.tool-button").bounding_box()
    assert abs(edit["y"] - delete["y"]) < 2 and delete["x"] > edit["x"]  # side by side
    expect(page.locator(".entry-table thead th", has_text="Quantity").first).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".entry-table thead").first).to_be_hidden()
    note = row.locator("td.entry-note").bounding_box()
    assert note["width"] > 150  # the note wraps by word, not one letter per line
    where, quantity = row.locator("td").nth(1).bounding_box(), row.locator("td.num").bounding_box()
    assert abs(where["y"] - quantity["y"]) < 4  # location and quantity share the card's first line
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
    rows = page.locator("#risks-table tbody tr:visible")
    expect(rows).to_have_count(2)
    expect(page.locator("#risks-table-search")).to_be_visible()
    page.get_by_role("button", name="Past target date").click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Weekend access")
    expect(page).to_have_url(re.compile(r"\?filter=overdue$"))
    page.get_by_role("button", name="All open").click()
    page.get_by_placeholder("Search risks").fill("supplier")
    expect(rows).to_have_count(1)
    # The chip counts follow the search.
    expect(page.get_by_role("button", name="Red")).to_contain_text("1")
    expect(page.get_by_role("button", name="Amber")).to_contain_text("0")
    page.get_by_placeholder("Search risks").fill("nothing like this")
    expect(page.get_by_text("No risks match this filter.")).to_be_visible()
    page.locator("[data-no-match] [data-clear-for]").click()
    expect(rows).to_have_count(2)
    expect(page.locator(".closed-block summary")).to_have_text("Closed risks (1)")
    assert_clean(page)


def test_risk_register_sorts_worst_first_and_by_column(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    refs = page.locator("#risks-table tbody tr:visible .risk-ref")
    expect(refs).to_have_text(["R1", "R2"])  # Red before Amber
    expect(page.locator("#risks-table th[data-sort-default]")).to_have_attribute("aria-sort", "ascending")
    page.locator("#risks-table th", has_text="Ref").get_by_role("button").click()
    page.locator("#risks-table th", has_text="Ref").get_by_role("button").click()
    expect(refs).to_have_text(["R2", "R1"])
    expect(page).to_have_url(re.compile(r"\?sort=-ref$"))
    page.locator("#risks-table th", has_text="Target date").get_by_role("button").click()
    expect(refs).to_have_text(["R2", "R1"])  # the risk with no date comes last
    page.reload()
    expect(page.locator("#risks-table th", has_text="Target date")).to_have_attribute("aria-sort", "ascending")
    assert_clean(page)


def test_risk_register_pages_and_keeps_closed_risks_apart(page, live_server, seeded, db):
    for number in range(4, 34):
        db.add(Risk(tracker_id=seeded.tracker.id, ref=f"R{number}", description=f"Extra {number}", status="Open"))
    db.commit()
    open_page(page, live_server, seeded, "risks")
    expect(page.locator("#risks-table tbody tr:visible")).to_have_count(25)
    expect(page.locator("[data-pager-for='risks-table'] [data-pager-count]")).to_have_text(
        "Showing 1\u201325 of 32 risks"
    )
    page.locator("[data-pager-for='risks-table'] [data-pager-next]").click()
    expect(page.locator("#risks-table tbody tr:visible")).to_have_count(7)
    expect(page).to_have_url(re.compile(r"\?page=2$"))
    # The closed risks keep their own table and their own address keys.
    page.locator(".closed-block summary").click()
    expect(page.locator("#closed-risks-table tbody tr:visible")).to_have_count(1)
    expect(page.locator("[data-pager-for='closed-risks-table'] [data-pager-count]")).to_have_text(
        "Showing 1 of 1 closed risk"
    )
    page.locator("#closed-risks-table th", has_text="Ref").get_by_role("button").click()
    page.locator("#closed-risks-table th", has_text="Ref").get_by_role("button").click()
    expect(page).to_have_url(re.compile(r"\?page=2&closed-sort=-ref$"))
    assert_clean(page)


def test_risk_delete_asks_first(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    messages = []

    def answer(dialog, accept):
        messages.append(dialog.message)
        dialog.accept() if accept else dialog.dismiss()

    page.once("dialog", lambda dialog: answer(dialog, False))
    page.get_by_role("button", name="Delete risk R1").click()
    expect(page.locator("#risks-table tbody tr")).to_have_count(2)
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
    expect(page.locator(".group-total")).to_contain_text("All active locations")
    assert_clean(page)


def test_the_past_target_count_is_tinted_while_above_zero(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    overdue = page.locator('[data-status="overdue"] .chip-count')
    expect(overdue).to_have_class(re.compile(r"\bis-alert\b"))  # from the server, before the script runs
    page.get_by_placeholder("Search risks").fill("supplier")  # no overdue risk matches this search
    expect(overdue).to_have_text("0")
    expect(overdue).not_to_have_class(re.compile(r"\bis-alert\b"))
    page.get_by_placeholder("Search risks").fill("weekend")
    expect(overdue).to_have_class(re.compile(r"\bis-alert\b"))
    expect(page.locator('[data-status="red"] .chip-count')).not_to_have_class(re.compile(r"\bis-alert\b"))
    assert_clean(page)


def test_a_saved_view_of_the_closed_table_shows_it_open(page, live_server, seeded):
    open_page(page, live_server, seeded, "risks")
    expect(page.locator(".closed-block")).not_to_have_attribute("open", "")
    page.goto(f"{live_server}/trackers/{seeded.tracker.id}/risks?closed-sort=-ref")
    expect(page.locator(".closed-block")).to_have_attribute("open", "")
    expect(page.locator("#closed-risks-table tbody tr:visible")).to_have_count(1)
    assert_clean(page)
