"""The Permission sets cards in a real browser: live counts, "Changed" marks, the save note, and fit (database)."""

from __future__ import annotations

import re

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_ticking_updates_the_card_and_the_note(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    card = page.locator("article[data-set-card]", has_text="PMO")
    note = page.locator("[data-dirty-note]")
    expect(page.locator(".perm-card-count")).to_have_count(0)

    page.get_by_label("Manage users for PMO").check()
    expect(card).to_have_class(re.compile(r"\bis-changed\b"))
    expect(card.get_by_text("Changed")).to_be_visible()
    expect(note).to_have_text("Unsaved changes in 1 set")

    page.get_by_label("Manage users for PMO").uncheck()
    expect(card.get_by_text("Changed")).to_be_hidden()
    expect(note).to_have_text("No unsaved changes")

    page.get_by_label("Create trackers for PMO").check()
    page.get_by_role("button", name="Save permissions").click()
    expect(page.get_by_text("Saved the permissions.")).to_be_visible()
    expect(page.get_by_label("Create trackers for PMO")).to_be_checked()
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
def test_cards_fit_without_page_scroll(page, live_server, user_factory, give_set, size):
    give_set(
        ["manage_users", "manage_teams"],
        user=user_factory(),
        name=("Programme management office and delivery assurance " * 2)[:100],
    )
    give_set(["view_activity"], user=user_factory(), name="PMO")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    expect(page.locator("article[data-set-card]")).to_have_count(2)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_cards_scroll_clear_of_the_top_bar(page, live_server, user_factory):
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    margin = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.perm-card')).scrollMarginTop)")
    bar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert margin > bar


# Before the deferred script runs, tick a box as a browser does when it restores a form after a reload or Back.
RESTORED_TICK = """
document.addEventListener("readystatechange", function () {
  if (document.readyState !== "interactive") return;
  var box = document.querySelector("article[data-set-card] input[value=manage_users]");
  if (box) box.checked = true;
});
"""


def test_ticks_restored_by_the_browser_count_as_unsaved(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.add_init_script(RESTORED_TICK)
    page.goto(f"{live_server}/admin/permission-sets")
    card = page.locator("article[data-set-card]", has_text="PMO")
    expect(page.locator("[data-dirty-note]")).to_have_text("Unsaved changes in 1 set")
    expect(card.get_by_text("Changed")).to_be_visible()


def test_permission_rows_line_up_across_cards(page, live_server, db, user_factory, give_set):
    long = give_set(["view_activity"], user=user_factory(), name="PMO")
    long.description = "Programme management office: reads every tracker and the activity log. " * 3
    give_set(["manage_users"], user=user_factory(), name="Operations")
    db.commit()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    cards = page.locator(".perm-cards > .perm-card")
    expect(cards).to_have_count(3)  # Administrators, Operations, PMO
    tops = [cards.nth(k).bounding_box()["y"] for k in range(3)]
    assert max(tops) - min(tops) < 1  # the three sit side by side in one row
    # The same permission, the group headings and the card footers sit at the same height in every card.
    for selector in (".perm-group", ".perm-row", ".perm-card-foot"):
        heights = page.evaluate(
            """sel => [...document.querySelectorAll('.perm-cards > .perm-card')]
                .map(card => [...card.querySelectorAll(sel)].map(el => Math.round(el.getBoundingClientRect().top)))""",
            selector,
        )
        assert all(column == heights[0] for column in heights), (selector, heights)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_save_bar_is_frosted(page, live_server, user_factory, give_set, theme):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    page.get_by_label("Manage users for PMO").check()  # the bar shows only with a change
    page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
    bar = page.locator(".perm-save")
    blur = bar.evaluate("el => getComputedStyle(el).backdropFilter")
    assert re.search(r"blur\((1[2-9]|[2-9]\d)px\)", blur), blur  # a strong blur, as on an iPhone
    # Browsers report a mixed colour as rgba(r, g, b, a) or color(srgb r g b / a); the alpha is the 4th number.
    colour = bar.evaluate("el => getComputedStyle(el).backgroundColor")
    numbers = re.findall(r"[\d.]+", colour.replace("srgb", ""))
    alpha = float(numbers[3]) if len(numbers) > 3 else 1.0
    assert alpha <= 0.8, colour  # see-through enough for the cards to show behind it


def three_sets(give_set, user_factory):
    for name in ("PMO", "Operations", "Support"):
        give_set(["view_activity"], user=user_factory(), name=name)


def test_the_head_stays_pinned_under_the_top_bar(page, live_server, user_factory, give_set):
    three_sets(give_set, user_factory)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(300)
    bar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    head = page.evaluate("document.querySelector('.perm-head').getBoundingClientRect().top")
    assert abs(head - bar) <= 2, (head, bar)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_cards_form_one_sideways_row_with_a_third_of_the_next_showing(page, live_server, user_factory, give_set):
    three_sets(give_set, user_factory)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    boxes = page.evaluate(
        """() => { const row = document.querySelector('[data-permission-cards]').getBoundingClientRect();
          return {right: row.right, cards: [...document.querySelectorAll('.perm-cards > .perm-card')]
            .map(c => { const b = c.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width}; })}; }"""
    )
    cards = boxes["cards"]
    assert len(cards) == 4 and not page.locator(".perm-card-new").count()
    assert max(c["y"] for c in cards) - min(c["y"] for c in cards) < 1
    assert all(340 <= c["w"] <= 460 for c in cards), cards
    partly = next(c for c in cards if c["x"] < boxes["right"] < c["x"] + c["w"])
    shown = (boxes["right"] - partly["x"]) / partly["w"]
    assert 0.25 <= shown <= 0.45, shown
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def expect_poll(page, script, value, lower=False):
    """Wait for a number from a script to pass `value`; smooth scrolling takes a moment."""
    for _ in range(40):
        got = page.evaluate(script)
        if (got < value) if lower else (got > value):
            return
        page.wait_for_timeout(100)
    raise AssertionError((script, got))


def test_the_arrows_step_the_row_and_disable_at_the_ends(page, live_server, user_factory, give_set):
    three_sets(give_set, user_factory)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    before = page.get_by_role("button", name="Previous cards")
    after = page.get_by_role("button", name="Next cards")
    row = "document.querySelector('[data-permission-cards]').scrollLeft"
    expect(before).to_be_disabled()
    expect(after).to_be_enabled()
    after.click()
    expect_poll(page, row, 300)
    expect(before).to_be_enabled()
    for _ in range(4):
        if after.is_enabled():
            after.click()
            page.wait_for_timeout(500)
    expect(after).to_be_disabled()
    end = page.evaluate(row)
    before.click()
    expect_poll(page, row, end, lower=True)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_new_link_keeps_its_address_and_no_dashed_card_remains(page, live_server, user_factory):
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    expect(page.locator(".perm-card-new")).to_have_count(0)
    expect(page.get_by_role("link", name="New permission set")).to_have_attribute("href", "/admin/permission-sets/new")


def test_without_javascript_the_new_link_goes_to_the_create_page(browser, live_server, user_factory):
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        browser_sign_in(page, live_server, user_factory(is_admin=True))
        page.goto(f"{live_server}/admin/permission-sets")
        page.get_by_role("link", name="New permission set").click()
        expect(page).to_have_url(f"{live_server}/admin/permission-sets/new")
        expect(page.locator("#new-set-dialog")).to_be_hidden()
    finally:
        context.close()


def test_the_save_bar_shows_only_with_changes(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    bar = page.locator(".perm-save")
    expect(bar).to_be_hidden()
    box = page.get_by_label("Manage users for PMO")
    box.check()
    expect(bar).to_be_visible()
    expect(bar).to_contain_text("1 unsaved change in 1 set")
    page.get_by_label("Create trackers for PMO").check()
    expect(bar).to_contain_text("2 unsaved changes in 1 set")
    page.get_by_role("button", name="Discard").click()
    expect(box).not_to_be_checked()
    expect(page.get_by_label("Create trackers for PMO")).not_to_be_checked()
    expect(bar).to_be_hidden()
    expect(page.locator("[data-dirty-note]")).to_have_text("No unsaved changes")
    assert page.evaluate(UNLOAD_WARNS) is False
    box.check()
    expect(bar).to_be_visible()
    box.uncheck()
    expect(bar).to_be_hidden()
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


UNLOAD_WARNS = (
    "(() => { const e = new Event('beforeunload', {cancelable: true}); "
    "window.dispatchEvent(e); return e.defaultPrevented; })()"
)


def test_leaving_with_unsaved_ticks_warns(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    assert page.evaluate(UNLOAD_WARNS) is False
    page.get_by_label("Manage users for PMO").check()
    assert page.evaluate(UNLOAD_WARNS) is True


def test_the_cards_stack_on_a_phone(page, live_server, user_factory, give_set):
    three_sets(give_set, user_factory)
    page.set_viewport_size({"width": 390, "height": 844})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    xs = page.evaluate(
        "[...document.querySelectorAll('.perm-cards > .perm-card')].map(c => Math.round(c.getBoundingClientRect().x))"
    )
    assert len(set(xs)) == 1
    expect(page.get_by_role("button", name="Next cards")).to_be_hidden()


@pytest.mark.parametrize("width", [800, 720, 1000])
def test_the_pinned_head_stays_inside_the_page_at_middle_widths(page, live_server, user_factory, give_set, width):
    three_sets(give_set, user_factory)
    page.set_viewport_size({"width": width, "height": 900})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("document.querySelector('.perm-head').getBoundingClientRect().right <= window.innerWidth")


def test_discard_moves_the_focus_to_a_restored_tick(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    page.get_by_label("Manage users for PMO").check()
    page.get_by_role("button", name="Discard").click()
    expect(page.get_by_label("Manage users for PMO")).to_be_focused()


def test_a_refused_save_does_not_silence_the_warning(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    page.get_by_label("Manage users for PMO").check()
    page.evaluate(
        "document.getElementById('permission-cards-form').addEventListener('submit', e => e.preventDefault())"
    )
    page.evaluate("document.getElementById('permission-cards-form').requestSubmit()")
    assert page.evaluate(UNLOAD_WARNS) is True


# The card menus, the rename and delete pop-ups and the holders side panel.
def open_page(page, live_server, user_factory, query=""):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets{query}")


def clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def card_of(page, name):
    return page.locator("article[data-set-card]", has=page.get_by_role("heading", name=name, exact=True))


def test_the_card_menu_opens_with_three_items_and_closes_on_escape(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    expect(page.locator(".perm-card-builtin .perm-more")).to_have_count(0)
    more = card_of(page, "PMO").get_by_role("button", name="More for PMO")
    expect(more).to_have_attribute("aria-expanded", "false")
    more.click()
    expect(more).to_have_attribute("aria-expanded", "true")
    items = page.get_by_role("menuitem")
    expect(items).to_have_text(["Rename or edit description", "Holders and details", "Delete…"])
    expect(items.first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(items.nth(1)).to_be_focused()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")
    expect(items.nth(2)).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(more).to_be_focused()
    more.click()
    page.get_by_role("heading", name="Permission sets").click()
    expect(page.get_by_role("menu")).to_have_count(0)
    clean(page)


def test_rename_saves_the_new_name_and_description(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Rename or edit description").click()
    dialog = page.get_by_role("dialog", name="Rename or edit description")
    expect(dialog.get_by_label("Name")).to_have_value("PMO")
    dialog.get_by_label("Name").fill("   ")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_text("Enter a permission set name.")).to_be_visible()
    dialog.get_by_label("Name").fill("Delivery office")
    dialog.get_by_label("Description").fill("Runs delivery")
    dialog.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Saved the permission set details.")).to_be_visible()
    card = card_of(page, "Delivery office")
    expect(card.get_by_text("Runs delivery")).to_be_visible()
    expect(page.get_by_role("dialog", name="Rename or edit description")).to_have_count(0)
    expect(page.locator("dialog.perm-drawer")).to_be_visible()  # the redirect reopens the set's panel
    page.goto(f"{live_server}/admin/activity")
    expect(page.get_by_text("Delivery office").first).to_be_visible()
    clean(page)


def test_delete_shows_who_loses_what_and_removes_the_card(page, live_server, user_factory, team_factory, give_set):
    team = team_factory()
    give_set(["view_activity", "manage_users"], team=team, name="PMO")
    give_set(["view_activity"], user=user_factory(), name="Keep")
    open_page(page, live_server, user_factory)
    card = card_of(page, "PMO")
    card.get_by_label("Create trackers for PMO").check()  # unsaved: not part of what is lost
    card.get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Delete…").click()
    dialog = page.get_by_role("dialog", name="Delete PMO?")
    expect(dialog).to_contain_text("This cannot be undone.")
    expect(dialog).to_contain_text("Held by 1 team. They lose:")
    expect(dialog.get_by_role("listitem")).to_have_text(["Manage users", "View activity"])
    expect(dialog).to_contain_text("The activity log records the deletion and each holder removed.")
    dialog.get_by_role("button", name="Cancel").click()
    expect(card).to_be_visible()
    card.get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Delete…").click()
    page.on("dialog", lambda d: d.accept())  # leaving with the unsaved tick warns; go ahead
    dialog.get_by_role("button", name="Delete set").click()
    expect(page.get_by_text("Deleted the permission set")).to_be_visible()
    expect(card_of(page, "PMO")).to_have_count(0)
    expect(card_of(page, "Keep")).to_have_count(1)
    clean(page)


def test_delete_of_a_set_nobody_holds_says_so(page, live_server, db, user_factory):
    from tracker.models import PermissionSet

    db.add(PermissionSet(name="Empty"))
    db.commit()
    open_page(page, live_server, user_factory)
    card_of(page, "Empty").get_by_role("button", name="More for Empty").click()
    page.get_by_role("menuitem", name="Delete…").click()
    expect(page.get_by_role("dialog")).to_contain_text("Nobody holds this set, so nobody loses anything.")
    clean(page)


def holders_set(give_set, user_factory, team_factory):
    team = team_factory(name="Delivery")
    person = user_factory(full_name="Priya Shah")
    permission_set = give_set(["view_activity", "manage_users"], team=team, name="PMO")
    return permission_set, person


@pytest.mark.parametrize("how", ["link", "menu"])
def test_holders_and_details_opens_the_side_panel(page, live_server, user_factory, team_factory, give_set, how):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    card = card_of(page, "PMO")
    if how == "link":
        card.get_by_role("link", name="Holders and details").click()
    else:
        card.get_by_role("button", name="More for PMO").click()
        page.get_by_role("menuitem", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("heading", name="PMO", exact=True)).to_be_visible()
    expect(panel.get_by_role("button", name="Remove")).to_have_count(1)
    expect(panel.locator(".panel-holders")).to_contain_text("Delivery")
    expect(panel.locator("ul.chips")).to_contain_text("View activity")
    expect(panel.locator("ul.chips")).to_contain_text("Manage users")
    assert "set=" in page.url
    clean(page)


def test_the_panel_remove_and_add_holder_come_back_with_the_panel_open(
    page, live_server, user_factory, team_factory, give_set
):
    _, person = holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    page.on("dialog", lambda d: d.accept())
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    panel.get_by_role("button", name="Remove").click()
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Nobody holds this set yet.")
    panel.get_by_label("Add a holder").select_option(label=f"{person.full_name} ({person.email})")
    panel.get_by_role("button", name="Add holder").click()
    expect(panel).to_be_visible()
    expect(panel.locator(".panel-holders")).to_contain_text("Priya Shah")
    expect(card_of(page, "PMO")).to_contain_text("Held by 1 person")
    clean(page)


def test_the_panel_menu_renames_and_deletes(page, live_server, user_factory, team_factory, give_set):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    panel.get_by_role("button", name="More for PMO").click()
    expect(panel.get_by_role("menuitem")).to_have_text(["Rename or edit description", "Delete…"])
    panel.get_by_role("menuitem", name="Rename or edit description").click()
    dialog = page.get_by_role("dialog", name="Rename or edit description")
    dialog.get_by_label("Name").fill("Delivery office")
    dialog.get_by_role("button", name="Save").click()
    expect(panel).to_be_visible()  # the redirect reopens it
    expect(panel.get_by_role("heading", name="Delivery office", exact=True)).to_be_visible()
    panel.get_by_role("button", name="More for Delivery office").click()
    panel.get_by_role("menuitem", name="Delete…").click()
    page.get_by_role("dialog", name="Delete Delivery office?").get_by_role("button", name="Delete set").click()
    expect(page.locator("dialog[open]")).to_have_count(0)
    expect(page.locator("article[data-set-card]")).to_have_count(0)
    expect(page).not_to_have_url(re.compile(r"set="))
    clean(page)


def test_escape_the_backdrop_and_the_cross_close_the_panel(page, live_server, user_factory, team_factory, give_set):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    link = card_of(page, "PMO").get_by_role("link", name="Holders and details")
    panel = page.locator("dialog.perm-drawer")
    for close in ("escape", "backdrop", "cross"):
        link.click()
        expect(panel).to_be_visible()
        assert "set=" in page.url
        if close == "escape":
            page.keyboard.press("Escape")
        elif close == "backdrop":
            page.mouse.click(40, 400)
        else:
            panel.get_by_role("button", name="Close").click()
        expect(panel).to_be_hidden()
        expect(page).not_to_have_url(re.compile(r"set="))
        expect(link).to_be_focused()
    clean(page)


@pytest.mark.parametrize("query", ["?set=999999", "?set=abc", "?set=", "?set=1e1", "?set=-1"])
def test_a_bad_set_in_the_address_opens_nothing(page, live_server, user_factory, give_set, query):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory, query)
    expect(page.locator("article[data-set-card]")).to_have_count(1)
    expect(page.locator("dialog[open]")).to_have_count(0)
    clean(page)


def test_the_address_opens_the_panel_on_load(page, live_server, user_factory, give_set):
    permission_set = give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory, f"?set={permission_set.id}")
    expect(page.locator("dialog.perm-drawer")).to_be_visible()
    clean(page)


def test_a_failed_load_offers_the_sets_own_page(page, live_server, user_factory, give_set):
    permission_set = give_set(["view_activity"], user=user_factory(), name="PMO")
    page.route("**/panel", lambda route: route.abort())
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    expect(panel).to_contain_text("The holders could not be loaded.")
    link = panel.get_by_role("link", name="Open the set's own page")
    expect(link).to_have_attribute("href", f"/admin/permission-sets/{permission_set.id}")


def test_the_keyboard_works_inside_the_panel_without_closing_it(
    page, live_server, user_factory, team_factory, give_set
):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    page.on("dialog", lambda d: d.dismiss())  # the Remove confirmation
    card_of(page, "PMO").get_by_role("link", name="Holders and details").focus()
    page.keyboard.press("Enter")
    panel = page.locator("dialog.perm-drawer")
    expect(panel).to_be_visible()
    more = panel.get_by_role("button", name="More for PMO")
    more.focus()
    page.keyboard.press("Enter")
    expect(more).to_have_attribute("aria-expanded", "true")
    expect(panel).to_be_visible()
    page.keyboard.press("Escape")
    expect(more).to_be_focused()
    panel.get_by_role("button", name="Remove").focus()
    page.keyboard.press("Enter")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("button", name="Remove")).to_have_count(1)  # declined, so still held
    clean(page)


@pytest.mark.parametrize("how", ["cancel", "escape"])
def test_focus_returns_to_the_menu_button_when_a_popup_closes_unsaved(page, live_server, user_factory, give_set, how):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    more = card_of(page, "PMO").get_by_role("button", name="More for PMO")
    for item, name in (("Rename or edit description", "Rename or edit description"), ("Delete…", "Delete PMO?")):
        more.click()
        page.get_by_role("menuitem", name=item).click()
        dialog = page.get_by_role("dialog", name=name)
        expect(dialog).to_be_visible()
        if how == "cancel":
            dialog.get_by_role("button", name="Cancel").click()
        else:
            page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(more).to_be_focused()
    clean(page)


def test_an_expired_session_does_not_fill_the_panel_with_the_sign_in_page(page, live_server, user_factory, give_set):
    permission_set = give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    page.route(
        "**/panel",
        lambda route: route.fulfill(status=200, content_type="text/html", body="<form><input name=email></form>"),
    )
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    expect(panel).to_contain_text("The holders could not be loaded.")
    expect(panel.locator("input[name=email]")).to_have_count(0)
    expect(panel.get_by_role("link", name="Open the set's own page")).to_have_attribute(
        "href", f"/admin/permission-sets/{permission_set.id}"
    )


def test_a_click_on_empty_space_inside_the_panel_keeps_it_open(page, live_server, user_factory, team_factory, give_set):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    expect(panel.get_by_role("button", name="Remove")).to_be_visible()
    box = panel.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] - 40)
    page.mouse.click(box["x"] + 0.5, box["y"] + box["height"] / 2)  # the left border
    expect(panel).to_be_visible()
    page.mouse.click(40, 400)
    expect(panel).to_be_hidden()
    clean(page)


# --- New permission set in four steps ---------------------------------------------------------------------------


def open_new(page, live_server, user_factory):
    open_page(page, live_server, user_factory)
    page.get_by_role("link", name="New permission set").click()
    dialog = page.locator("#new-set-dialog")
    expect(dialog).to_be_visible()
    return dialog


def progress(dialog):
    return dialog.locator(".wizard-steps").evaluate("e => e.style.getPropertyValue('--progress')")


def step_name(dialog, name="Details"):
    dialog.get_by_label("Name", exact=True).fill(name)


def test_new_opens_the_pop_up_at_step_one(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    dialog = open_new(page, live_server, user_factory)
    expect(page).to_have_url(f"{live_server}/admin/permission-sets")
    expect(dialog.get_by_role("heading", name="New permission set")).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_be_focused()
    expect(dialog.locator("[data-step-dot][aria-current=step]")).to_have_text("1Details")
    expect(dialog.get_by_role("button", name="Back")).to_be_hidden()
    expect(dialog.get_by_role("button", name="Next")).to_be_visible()
    clean(page)


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        ("", "Give the set a name."),
        ("   ", "Give the set a name."),
        ("  pmo ", "A permission set with this name already exists."),
    ],
)
def test_step_one_refuses_an_empty_or_taken_name(page, live_server, user_factory, give_set, typed, message):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    dialog = open_new(page, live_server, user_factory)
    dialog.get_by_label("Name", exact=True).fill(typed)
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_text(message)).to_be_visible()
    expect(dialog.locator("[data-step='1']")).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_be_focused()
    step_name(dialog, "Fresh")
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.locator("[data-step='2']")).to_be_visible()
    clean(page)


def test_the_step_bar_fills_a_third_per_step_with_ticks_that_go_back(page, live_server, user_factory):
    dialog = open_new(page, live_server, user_factory)
    assert progress(dialog) == "0"
    step_name(dialog, "Auditors")
    dialog.get_by_role("button", name="Next").click()
    assert progress(dialog) == str(1 / 3)
    expect(dialog.locator("[data-step-dot='1']")).to_have_text("\u2713Details")
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Skip for now").click()
    assert progress(dialog) == "1"
    expect(dialog.locator("[data-step='4']")).to_be_visible()
    dialog.locator("[data-step-dot='2']").click()
    expect(dialog.locator("[data-step='2']")).to_be_visible()
    assert progress(dialog) == str(1 / 3)
    expect(dialog.locator("[data-step-dot='1']")).to_have_text("\u2713Details")
    dialog.locator("[data-step-dot='1']").focus()
    page.keyboard.press("Enter")
    expect(dialog.locator("[data-step='1']")).to_be_visible()
    assert progress(dialog) == "0"
    clean(page)


def test_step_two_counts_the_ticks_and_warns_about_users_with_teams(page, live_server, user_factory):
    dialog = open_new(page, live_server, user_factory)
    step_name(dialog)
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.get_by_text("0 of 8 ticked")).to_be_visible()
    expect(dialog.get_by_text("Holding both Manage users and Manage teams")).to_be_hidden()
    dialog.locator("#new-perm-manage_users").check()
    expect(dialog.get_by_text("1 of 8 ticked")).to_be_visible()
    expect(dialog.get_by_text("Holding both Manage users and Manage teams")).to_be_hidden()
    dialog.locator("#new-perm-manage_teams").check()
    expect(dialog.get_by_text("2 of 8 ticked")).to_be_visible()
    expect(dialog.get_by_text("Holding both Manage users and Manage teams")).to_be_visible()
    dialog.locator("#new-perm-manage_teams").uncheck()
    expect(dialog.get_by_text("Holding both Manage users and Manage teams")).to_be_hidden()
    clean(page)


def holders_world(user_factory, team_factory):
    parent = team_factory(name="Operations")
    team_factory(name="Delivery", parent=parent)
    user_factory(full_name="Priya Shah", email="priya.shah@example.com")
    user_factory(full_name="Sam Patel", email="sam.patel@example.com")


def to_step_three(dialog):
    step_name(dialog)
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Next").click()


def test_step_three_searches_teams_and_people_and_shows_chips(page, live_server, user_factory, team_factory):
    holders_world(user_factory, team_factory)
    dialog = open_new(page, live_server, user_factory)
    to_step_three(dialog)
    holders = dialog.locator(".wizard-holders li:visible")
    expect(dialog.get_by_role("button", name="Skip for now")).to_be_visible()
    expect(dialog.get_by_role("button", name="Next")).to_be_hidden()
    expect(dialog.get_by_text("Delivery")).to_be_visible()
    expect(dialog.get_by_text("priya.shah@example.com")).to_be_visible()
    dialog.get_by_label("Search teams and people").fill("priya")
    expect(holders).to_have_count(1)
    holders.get_by_label("Priya Shah").check()
    dialog.get_by_label("Search teams and people").fill("deliv")
    expect(holders).to_have_count(1)
    dialog.get_by_label("Search teams and people").fill("")
    dialog.get_by_label("Delivery").check()
    picked = dialog.locator("[data-holder-picked]")
    expect(picked.get_by_role("button")).to_have_count(2)
    expect(dialog.get_by_role("button", name="Skip for now")).to_be_hidden()
    expect(dialog.get_by_role("button", name="Next")).to_be_visible()
    picked.get_by_role("button", name="Remove Priya Shah").click()
    expect(picked.get_by_role("button")).to_have_count(1)
    expect(dialog.get_by_label("Priya Shah")).not_to_be_checked()
    clean(page)


def test_the_review_shows_three_blocks_and_edit_goes_back(page, live_server, user_factory, team_factory):
    holders_world(user_factory, team_factory)
    dialog = open_new(page, live_server, user_factory)
    dialog.get_by_label("Name", exact=True).fill("Auditors")
    dialog.get_by_role("button", name="Next").click()
    dialog.locator("#new-perm-manage_users").check()
    dialog.locator("#new-perm-view_activity").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_label("Sam Patel").check()
    dialog.get_by_label("Delivery").check()
    dialog.get_by_role("button", name="Next").click()
    review = dialog.locator("[data-step='4']")
    expect(review.get_by_role("heading", name="Set")).to_be_visible()
    expect(review.locator(".review-name")).to_have_text("Auditors")
    expect(review.get_by_text("No description.")).to_be_visible()
    expect(review.get_by_role("heading", name="Permissions")).to_be_visible()
    expect(review.get_by_text("2 of 8")).to_be_visible()
    expect(review.locator(".review-group li")).to_have_text(["Manage users", "View activity"])
    expect(review.locator(".review-left")).to_contain_text("Not included: ")
    expect(review.locator(".review-left")).not_to_contain_text("Manage users")
    expect(review.get_by_role("heading", name="Holders")).to_be_visible()
    expect(review.locator(".review-chips li")).to_have_count(2)
    expect(review.locator(".review-chips")).to_contain_text("Sam Patel")
    expect(review.locator(".review-chips")).to_contain_text("Delivery")
    expect(review.locator(".review-chips")).to_contain_text("team")
    expect(review.get_by_text("Nothing is saved until you press Create permission set.")).to_be_visible()
    review.get_by_role("button", name="Edit").nth(1).click()
    expect(dialog.locator("[data-step='2']")).to_be_visible()
    dialog.locator("#new-perm-manage_users").uncheck()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Next").click()
    expect(review.locator(".review-group li")).to_have_text(["View activity"])
    review.get_by_role("button", name="Edit").nth(0).click()
    expect(dialog.locator("[data-step='1']")).to_be_visible()
    expect(review).to_be_hidden()
    clean(page)


def test_create_saves_the_set_and_opens_its_panel(page, live_server, user_factory, team_factory):
    holders_world(user_factory, team_factory)
    dialog = open_new(page, live_server, user_factory)
    dialog.get_by_label("Name", exact=True).fill("Auditors")
    dialog.get_by_label("Description").fill("Read only people")
    dialog.get_by_role("button", name="Next").click()
    dialog.locator("#new-perm-manage_users").check()
    dialog.locator("#new-perm-view_activity").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_label("Priya Shah").check()
    dialog.get_by_label("Delivery").check()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Create permission set").click()
    panel = page.locator("dialog.perm-drawer")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("heading", name="Auditors", exact=True)).to_be_visible()
    expect(panel.locator(".panel-holders")).to_contain_text("Delivery")
    expect(panel.locator(".panel-holders")).to_contain_text("Priya Shah")
    expect(panel.locator("ul.chips")).to_contain_text("Manage users")
    assert "set=" in page.url
    panel.get_by_role("button", name="Close").click()
    card = card_of(page, "Auditors")
    expect(card.get_by_label("Manage users for Auditors")).to_be_checked()
    expect(card.get_by_label("View activity for Auditors")).to_be_checked()
    expect(card.get_by_label("Manage teams for Auditors")).not_to_be_checked()
    expect(card).to_contain_text("Read only people")
    clean(page)


def test_the_pop_up_resets_each_time_and_closing_discards_the_draft(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    dialog = open_new(page, live_server, user_factory)
    step_name(dialog, "Draft")
    dialog.get_by_role("button", name="Next").click()
    dialog.locator("#new-perm-manage_users").check()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("link", name="New permission set")).to_be_focused()
    page.get_by_role("link", name="New permission set").click()
    expect(dialog.locator("[data-step='1']")).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("")
    assert progress(dialog) == "0"
    step_name(dialog, "Again")
    dialog.get_by_role("button", name="Next").click()
    expect(dialog.locator("#new-perm-manage_users")).not_to_be_checked()
    expect(dialog.get_by_text("0 of 8 ticked")).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    clean(page)


def test_enter_in_the_name_goes_next_and_never_creates(page, live_server, user_factory):
    dialog = open_new(page, live_server, user_factory)
    step_name(dialog, "Quiet")
    page.keyboard.press("Enter")
    expect(dialog.locator("[data-step='2']")).to_be_visible()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_label("Search teams and people").focus()
    page.keyboard.press("Enter")
    expect(dialog.locator("[data-step='3']")).to_be_visible()
    assert page.url == f"{live_server}/admin/permission-sets"
    clean(page)


def test_create_with_unsaved_ticks_still_warns_on_leaving(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    dialog = open_new(page, live_server, user_factory)
    page.locator("[data-set-card] input[value=manage_users]").first.evaluate(
        "box => { box.checked = true; box.dispatchEvent(new Event('change', {bubbles: true})); }"
    )
    step_name(dialog, "Late")
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Skip for now").click()
    kinds = []

    def stay(prompt):
        kinds.append(prompt.type)
        prompt.dismiss()

    page.on("dialog", stay)
    dialog.get_by_role("button", name="Create permission set").click()
    page.wait_for_timeout(500)
    assert kinds == ["beforeunload"]
    expect(dialog).to_be_visible()


def test_the_pop_up_fits_a_phone(page, live_server, user_factory, team_factory):
    holders_world(user_factory, team_factory)
    page.set_viewport_size({"width": 390, "height": 844})
    dialog = open_new(page, live_server, user_factory)
    to_step_three(dialog)
    dialog.get_by_role("button", name="Skip for now").click()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    box = dialog.bounding_box()
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390
    clean(page)


SUBMIT_TWICE = """
form => {
  const went = [];
  window.addEventListener("submit", e => went.push(!e.defaultPrevented));
  form.requestSubmit();
  form.requestSubmit();
  return went;
}
"""


def test_a_second_submit_of_create_is_ignored(page, live_server, user_factory, db):
    from sqlalchemy import func, select

    from tracker.models import PermissionSet

    dialog = open_new(page, live_server, user_factory)
    step_name(dialog, "Auditors")
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Skip").click()
    went = dialog.locator("form").evaluate(SUBMIT_TWICE)
    assert went == [True, False]
    expect(page.get_by_text("Created the permission set Auditors.")).to_be_visible()
    expect(page.get_by_text("already exists")).to_have_count(0)
    assert db.scalar(select(func.count()).select_from(PermissionSet).where(PermissionSet.name == "Auditors")) == 1
    clean(page)


def test_a_double_click_on_create_creates_one_set(page, live_server, user_factory, db):
    from sqlalchemy import func, select

    from tracker.models import PermissionSet

    dialog = open_new(page, live_server, user_factory)
    step_name(dialog, "Auditors")
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Next").click()
    dialog.get_by_role("button", name="Skip").click()
    dialog.get_by_role("button", name="Create permission set").dblclick()
    expect(page.get_by_text("Created the permission set Auditors.")).to_be_visible()
    expect(page.get_by_text("already exists")).to_have_count(0)
    assert db.scalar(select(func.count()).select_from(PermissionSet).where(PermissionSet.name == "Auditors")) == 1
    clean(page)


def test_a_second_submit_of_delete_is_ignored(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Delete…").click()
    dialog = page.get_by_role("dialog", name="Delete PMO?")
    assert dialog.locator("form").evaluate(SUBMIT_TWICE) == [True, False]
    expect(page.get_by_text("Deleted the permission set PMO.")).to_be_visible()
    expect(page.get_by_text("Not found")).to_have_count(0)
    clean(page)


def test_a_second_submit_of_rename_is_ignored(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Rename or edit description").click()
    dialog = page.get_by_role("dialog", name="Rename or edit description")
    dialog.get_by_label("Name").fill("Delivery office")
    assert dialog.locator("form").evaluate(SUBMIT_TWICE) == [True, False]
    expect(page.get_by_text("Saved the permission set details.")).to_be_visible()
    expect(page.get_by_text("No changes")).to_have_count(0)
    clean(page)


def test_rename_refuses_a_name_another_set_has(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    give_set(["view_activity"], user=user_factory(), name="Audit")
    open_page(page, live_server, user_factory)
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    card_of(page, "PMO").get_by_role("button", name="More for PMO").click()
    page.get_by_role("menuitem", name="Rename or edit description").click()
    dialog = page.get_by_role("dialog", name="Rename or edit description")
    dialog.get_by_label("Name").fill("audit")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_text("A permission set with this name already exists.")).to_be_visible()
    assert posts == []
    dialog.get_by_label("Name").fill("pmo")  # its own name, in another case, is fine
    dialog.get_by_role("button", name="Save").click()
    expect(page.get_by_text("Saved the permission set details.")).to_be_visible()
    clean(page)


def test_the_panel_is_named_after_its_set_and_announces_only_a_status(
    page, live_server, user_factory, team_factory, give_set
):
    holders_set(give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    expect(page.get_by_role("dialog", name="PMO", exact=True)).to_be_visible()
    expect(page.locator("dialog.perm-drawer [role=status]")).to_have_count(1)
    expect(page.locator("dialog.perm-drawer [aria-live]:not([data-pager-count])")).to_have_count(0)


# --- The holders table (the set's own page and the side panel) -------------------------------------------------------


def three_holders(db, give_set, user_factory, team_factory):
    """PMO held by the team Delivery and the people Priya Shah and Anna Weber."""
    from tracker.models import PermissionSetHolder

    team = team_factory(name="Delivery")
    permission_set = give_set(["view_activity"], team=team, name="PMO")
    for name in ("Priya Shah", "Anna Weber"):
        db.add(PermissionSetHolder(set_id=permission_set.id, user_id=user_factory(full_name=name).id))
    db.commit()
    return permission_set


def chip_counts(scope):
    return [" ".join(t.split()) for t in scope.locator("[data-status-for] .chip").all_inner_texts()]


def test_the_sets_own_page_holders_table_searches_filters_sorts_and_keeps_the_address(
    page, live_server, user_factory, team_factory, give_set, db
):
    permission_set = three_holders(db, give_set, user_factory, team_factory)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets/{permission_set.id}")
    table = page.locator("#holders-table")
    rows = table.locator("tbody tr:visible")
    expect(rows).to_have_count(3)
    assert chip_counts(page) == ["All 3", "People 2", "Teams 1"]
    assert " ".join(page.locator("[data-pager-count]").inner_text().split()) == "Showing 3 of 3 holders"

    page.locator("#holders-table-search").fill("priya")
    expect(rows).to_have_count(1)
    assert chip_counts(page) == ["All 1", "People 1", "Teams 0"]
    assert "q=priya" in page.url
    page.get_by_role("button", name="Clear filters").first.click()
    expect(rows).to_have_count(3)

    page.locator('[data-status-for] button[data-status="teams"]').click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Delivery")
    assert "filter=teams" in page.url
    page.locator('[data-status-for] button[data-status="all"]').click()

    table.locator('button[data-sort="name"]').click()
    assert table.locator("tbody tr:visible .cell-title, tbody tr:visible .member-name").all_inner_texts() == [
        "Anna Weber",
        "Delivery",
        "Priya Shah",
    ]
    assert "sort=name" in page.url
    clean(page)


def test_the_panels_holders_table_works_and_leaves_the_address_to_the_panel(
    page, live_server, user_factory, team_factory, give_set, db
):
    three_holders(db, give_set, user_factory, team_factory)
    open_page(page, live_server, user_factory)
    page.on("dialog", lambda d: d.accept())
    card_of(page, "PMO").get_by_role("link", name="Holders and details").click()
    panel = page.locator("dialog.perm-drawer")
    table = panel.locator("table.panel-holders")
    rows = table.locator("tbody tr:visible")
    expect(rows).to_have_count(3)
    expect(panel.locator("[data-search-for]")).to_be_visible()  # set up after the fragment arrived
    assert chip_counts(panel) == ["All 3", "People 2", "Teams 1"]
    panel_url = page.url
    assert page.url.split("?", 1)[1].startswith("set=")

    panel.get_by_role("searchbox").fill("priya")
    expect(rows).to_have_count(1)
    panel.locator('[data-status-for] button[data-status="people"]').click()
    expect(rows).to_have_count(1)
    table.locator('button[data-sort="name"]').click()
    assert page.url == panel_url  # no q, filter or sort in the address; ?set= still owns the panel

    # A Remove still posts, returns to ?set=<id> and the new table is set up too.
    panel.get_by_role("searchbox").fill("")
    panel.locator('[data-status-for] button[data-status="all"]').click()
    panel.locator("tbody tr", has_text="Priya Shah").get_by_role("button", name="Remove").click()
    expect(panel).to_be_visible()
    expect(table.locator("tbody tr")).to_have_count(2)
    assert chip_counts(panel) == ["All 2", "People 1", "Teams 1"]
    assert page.url.split("?", 1)[1].startswith("set=")
    assert "q=" not in page.url and "filter=" not in page.url
    clean(page)
