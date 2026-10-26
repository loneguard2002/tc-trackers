"""Sortable, filterable tables (Tabulator) in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import csv
from datetime import date
from types import SimpleNamespace

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER, WEEKS

from tracker.models import CompletionEntry, Group, Risk, Week

pytestmark = pytest.mark.browser

QUANTITY = ".tabulator-row .tabulator-cell[tabulator-field='c3']"


@pytest.fixture
def seeded(db, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Table tracker", first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    ld5 = Group(tracker_id=tracker.id, name="LD5", baseline=100, sort_order=1)
    ld6 = Group(tracker_id=tracker.id, name="<i>LD6</i>", baseline=50, sort_order=2)
    db.add_all([ld5, ld6])
    db.flush()
    for week in WEEKS:
        db.add(Week(tracker_id=tracker.id, week_ending=week, target=10))
    for group, quantity, day, week, note in (
        (ld5, 5, date(2026, 9, 3), WEEKS[0], "alpha"),
        (ld5, 3, date(2026, 9, 10), WEEKS[1], "beta"),
        (ld6, 9, date(2026, 9, 17), WEEKS[2], "gamma"),
    ):
        db.add(
            CompletionEntry(
                tracker_id=tracker.id, group_id=group.id, quantity=quantity, entry_date=day, week_ending=week, note=note
            )
        )
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="Supplier delay", status="Open", rag="Red"))
    db.commit()
    editor = user_factory()
    grant(editor, tracker, "editor")
    return SimpleNamespace(tracker=tracker, editor=editor)


def open_page(page, base_url, seeded, path):
    page.add_init_script(RECORDER)
    browser_sign_in(page, base_url, seeded.editor)
    page.goto(f"{base_url}/trackers/{seeded.tracker.id}/{path}")
    page.wait_for_selector(".tabulator-row")


def test_location_filter_narrows_rows(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    page.locator(".tabulator-col[tabulator-field='c2'] .tabulator-header-filter input").click()
    page.locator(".tabulator-edit-list-item", has_text="LD5").first.click()
    expect(page.locator(".tabulator-row")).to_have_count(2)


def test_quantity_sorts_numerically(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    page.locator(".tabulator-col[tabulator-field='c3'] .tabulator-col-title").click()
    assert page.locator(QUANTITY).all_inner_texts() == ["3", "5", "9"]


def test_markup_in_names_is_shown_as_text(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    expect(page.locator(".tabulator-row", has_text="<i>LD6</i>")).to_have_count(1)
    assert page.locator(".tabulator-row i").count() == 0


def test_markup_in_filter_list_is_shown_as_text(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    page.locator(".tabulator-col[tabulator-field='c2'] .tabulator-header-filter input").click()
    items = page.locator(".tabulator-edit-list .tabulator-edit-list-item")
    expect(items.filter(has_text="<i>LD6</i>")).to_have_count(1)
    assert page.locator(".tabulator-edit-list i").count() == 0


def test_markup_in_column_titles_is_shown_as_text(page, live_server, seeded, db):
    seeded.tracker.group_label = "<b>Site</b>"
    db.commit()
    open_page(page, live_server, seeded, "entries")
    expect(page.locator(".tabulator-col-title", has_text="<b>Site</b>")).to_have_count(1)
    assert page.locator(".tabulator-header b").count() == 0


def test_delete_still_works_in_an_enhanced_row(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    page.locator(".tabulator-row", has_text="gamma").get_by_role("button", name="Delete").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".tabulator-row")).to_have_count(2)
    expect(page.locator(".tabulator-row", has_text="gamma")).to_have_count(0)


def test_csv_download(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    with page.expect_download() as info:
        page.get_by_role("button", name="Download CSV").click()
    assert info.value.suggested_filename == "entries.csv"
    with open(info.value.path(), encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["Date", "Week ending", "Location", "Quantity", "Note"]
    assert len(rows) == 4


def assert_clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_tables_raise_no_policy_errors(page, live_server, seeded):
    open_page(page, live_server, seeded, "entries")
    page.locator(".tabulator-col[tabulator-field='c2'] .tabulator-header-filter input").click()
    expect(page.locator(".tabulator-edit-list")).to_be_visible()
    assert_clean(page)
    for path in ("risks", "report"):
        page.goto(f"{live_server}/trackers/{seeded.tracker.id}/{path}")
        page.wait_for_selector(".tabulator-row")
        assert_clean(page)
    expect(page.locator(".report .tabulator")).to_have_count(2)
