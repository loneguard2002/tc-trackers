"""The Teams Whole structure layer in a browser (spec 2026-11-26-teams-simple-redesign-design.md 4.9): opening and
closing, the left-to-right layout, dotted lines for shared teams, lighting, fit and zoom, folding and search, each
without a Content Security Policy violation or a script error (database)."""

from __future__ import annotations

import re

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER
from test_teams_new_view import swaps  # noqa: F401  (the fixture)

from tracker.models import Team, TeamParent

pytestmark = pytest.mark.browser


@pytest.fixture
def admin_page(page, live_server, user_factory):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True, full_name="Admin Person"))
    page.goto(f"{live_server}/admin/teams?view=new")  # the New view is kept for the rest of the test
    return page


def clean(page):
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def open_layer(page):
    page.get_by_role("link", name="Whole structure").click()
    layer = page.locator("#whole-structure")
    expect(layer).to_be_visible()
    return layer


def box(page, name: str):
    return page.locator(".structure-box", has=page.locator(".structure-box-name", has_text=re.compile(f"^{name}$")))


def centre(locator) -> tuple[float, float]:
    rect = locator.bounding_box()
    return rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2


# --- Open, lay out, draw, close -------------------------------------------------------------------------------------


def test_the_button_opens_the_layer_with_every_team(admin_page, live_server, team_factory, swaps):  # noqa: F811
    team_factory("APAC Desk")
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    expect(admin_page.locator(".structure-box")).to_have_count(4)
    expect(admin_page.locator("[data-structure-stats]")).to_have_text("4 teams · 3 levels shown · 0 shared")
    expect(admin_page.locator(".structure-level")).to_have_text(["Top", "Level 2", "Level 3"])
    expect(box(admin_page, "London Swaps")).to_have_class(re.compile(r"\bis-current\b"))
    clean(admin_page)


def test_left_to_right_places_levels_in_columns_and_top_to_bottom_in_rows(
    admin_page,
    live_server,
    swaps,  # noqa: F811
):
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    parent, child = box(admin_page, "EMEA Rates"), box(admin_page, "London Swaps")
    assert centre(child)[0] > centre(parent)[0]
    admin_page.get_by_role("button", name="Top to bottom").click()
    expect(admin_page.locator('[data-direction="tb"]')).to_have_attribute("aria-pressed", "true")
    expect(admin_page.locator('[data-direction="lr"]')).to_have_attribute("aria-pressed", "false")
    assert centre(child)[1] > centre(parent)[1]
    clean(admin_page)


def test_shared_team_gets_a_dotted_line_and_an_amber_edge(admin_page, live_server, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    shared = team_factory("Shared", parents=(alpha, beta), main=alpha)
    admin_page.goto(f"{live_server}/admin/teams/{alpha.id}")
    open_layer(admin_page)
    dotted = admin_page.locator("path.structure-line.is-dotted")
    expect(dotted).to_have_count(1)
    expect(dotted).to_have_attribute("data-from", str(beta.id))
    expect(dotted).to_have_attribute("data-to", str(shared.id))
    expect(admin_page.locator("circle.structure-line-end")).to_have_count(1)
    solid = admin_page.locator("path.structure-line.is-solid")
    expect(solid).to_have_count(1)
    expect(solid).to_have_attribute("data-from", str(alpha.id))
    expect(box(admin_page, "Shared")).to_have_class(re.compile(r"\bis-shared\b"))
    expect(admin_page.locator("[data-structure-stats]")).to_have_text("3 teams · 2 levels shown · 1 shared")
    clean(admin_page)


def test_pointing_at_a_box_lights_its_lines(admin_page, live_server, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(alpha, beta), main=alpha)
    admin_page.goto(f"{live_server}/admin/teams/{alpha.id}")
    open_layer(admin_page)
    box(admin_page, "Shared").hover()
    expect(admin_page.locator("path.structure-line.is-lit")).to_have_count(2)
    expect(box(admin_page, "Beta")).to_have_class(re.compile(r"\bis-linked\b"))
    expect(box(admin_page, "Alpha")).to_have_class(re.compile(r"\bis-linked\b"))
    clean(admin_page)


def test_escape_closes_and_focus_returns_to_the_button(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    layer = open_layer(admin_page)
    expect(admin_page.locator("#structure-find")).to_be_focused()
    admin_page.keyboard.press("Tab")  # Tab moves on through the layer's controls
    admin_page.keyboard.press("Escape")
    expect(layer).to_be_hidden()
    expect(admin_page.get_by_role("link", name="Whole structure")).to_be_focused()
    assert not admin_page.evaluate("document.body.classList.contains('structure-open')")
    clean(admin_page)


def test_the_box_links_are_reachable_by_keyboard(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    link = box(admin_page, "Global Markets").locator("a.structure-box-open")
    link.focus()
    expect(link).to_be_focused()
    assert link.evaluate("el => el.tabIndex") >= 0
    clean(admin_page)


def test_close_and_backdrop_close_the_layer(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    layer = open_layer(admin_page)
    admin_page.locator("[data-structure-close]").click()
    expect(layer).to_be_hidden()
    assert "#whole-structure" not in admin_page.url
    open_layer(admin_page)
    layer.click(position={"x": 2, "y": 2})  # the backdrop round the panel
    expect(layer).to_be_hidden()
    clean(admin_page)


def test_the_address_opens_the_layer(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}#whole-structure")
    expect(admin_page.locator("#whole-structure")).to_be_visible()
    expect(admin_page.locator(".structure-box")).to_have_count(3)
    clean(admin_page)


def test_the_old_address_opens_the_layer(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/structure")
    expect(admin_page.locator("#whole-structure")).to_be_visible()
    clean(admin_page)


def test_clicking_a_name_opens_the_team(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['top'].id}")
    open_layer(admin_page)
    box(admin_page, "London Swaps").locator("a.structure-box-open").click()
    admin_page.wait_for_url(re.compile(rf"/admin/teams/{swaps['team'].id}$"))
    expect(admin_page.locator("#whole-structure")).to_be_hidden()
    clean(admin_page)


def test_a_damaged_loop_is_left_out_without_errors(admin_page, live_server, db, swaps):  # noqa: F811
    x, y = Team(name="Loop X"), Team(name="Loop Y")
    db.add_all([x, y])
    db.flush()
    db.add_all(
        [TeamParent(team_id=x.id, parent_id=y.id, is_main=True), TeamParent(team_id=y.id, parent_id=x.id, is_main=True)]
    )
    db.commit()
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    expect(admin_page.locator(".structure-box")).to_have_count(3)
    expect(box(admin_page, "Loop X")).to_have_count(0)
    expect(box(admin_page, "Loop Y")).to_have_count(0)
    clean(admin_page)


def test_a_long_name_keeps_the_box_size(admin_page, live_server, team_factory):
    name = "Long " + "x" * 95
    team = team_factory(name)
    admin_page.goto(f"{live_server}/admin/teams/{team.id}")
    open_layer(admin_page)
    item = admin_page.locator(f'.structure-box[data-team-id="{team.id}"]')
    scale = admin_page.evaluate(
        "() => { var m = getComputedStyle(document.querySelector('[data-structure-stage]')).transform;"
        " return m === 'none' ? 1 : new DOMMatrix(m).a; }"
    )
    assert abs(item.bounding_box()["width"] - 200 * scale) <= 1
    expect(item.locator("a.structure-box-open")).to_have_attribute("title", name)
    clean(admin_page)


# --- Fit and zoom, fold, search -------------------------------------------------------------------------------------


def inside(inner: dict, outer: dict) -> bool:
    return (
        inner["x"] >= outer["x"] - 0.5
        and inner["y"] >= outer["y"] - 0.5
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 0.5
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + 0.5
    )


def test_fit_keeps_a_big_structure_on_screen(admin_page, live_server, team_factory):
    root = team_factory("Root")
    count = 1
    for chain in range(4):
        level2 = team_factory(f"Chain {chain} L2", parent=root)
        level3 = team_factory(f"Chain {chain} L3", parent=level2)
        level4 = team_factory(f"Chain {chain} L4", parent=level3)
        count += 3
        for leaf in range(7 if chain < 3 else 6):
            team_factory(f"Chain {chain} leaf {leaf}", parent=level4)
            count += 1
    assert count == 40
    admin_page.goto(f"{live_server}/admin/teams/{root.id}")
    open_layer(admin_page)
    expect(admin_page.locator(".structure-box")).to_have_count(40)
    expect(admin_page.locator("[data-structure-stats]")).to_have_text("40 teams · 5 levels shown · 0 shared")
    expect(admin_page.locator('[data-zoom="fit"]')).to_have_attribute("aria-pressed", "true")
    viewport = admin_page.locator("[data-structure-viewport]").bounding_box()
    outside = [
        i
        for i, rect in enumerate(b.bounding_box() for b in admin_page.locator(".structure-box").all())
        if not inside(rect, viewport)
    ]
    assert outside == []
    clean(admin_page)


def test_zoom_buttons_step_and_reset(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    percent = admin_page.locator('[data-zoom="reset"]')
    before = int(percent.inner_text().rstrip("%"))
    admin_page.get_by_role("button", name="Zoom in").click()
    expect(admin_page.locator('[data-zoom="fit"]')).to_have_attribute("aria-pressed", "false")
    expect(percent).not_to_have_text(f"{before}%")
    assert abs(int(percent.inner_text().rstrip("%")) - min(before * 1.2, 200)) <= 1
    percent.click()
    expect(percent).to_have_text("100%")
    admin_page.get_by_role("button", name="Zoom out").click()
    expect(percent).to_have_text("83%")
    admin_page.locator('[data-zoom="fit"]').click()
    expect(admin_page.locator('[data-zoom="fit"]')).to_have_attribute("aria-pressed", "true")
    expect(percent).to_have_text(f"{before}%")
    clean(admin_page)


def test_folding_a_branch_hides_it_and_says_how_many(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    admin_page.get_by_role("button", name="Fold EMEA Rates").click()
    expect(box(admin_page, "London Swaps")).to_have_count(0)
    unfold = admin_page.get_by_role("button", name="Unfold EMEA Rates")
    expect(unfold).to_have_text("+1")
    expect(admin_page.locator("[data-structure-stats]")).to_have_text("3 teams · 2 levels shown · 0 shared")
    expect(admin_page.get_by_role("button", name="Fold Global Markets")).to_have_text("−")
    unfold.click()
    expect(box(admin_page, "London Swaps")).to_have_count(1)
    expect(admin_page.locator("[data-structure-stats]")).to_have_text("3 teams · 3 levels shown · 0 shared")
    clean(admin_page)


def test_fold_all_keeps_the_top_two_levels(admin_page, live_server, team_factory):
    top = team_factory("Top team")
    second = team_factory("Second", parent=top)
    third = team_factory("Third", parent=second)
    team_factory("Fourth", parent=third)
    team_factory("Second B", parent=top)
    admin_page.goto(f"{live_server}/admin/teams/{top.id}")
    open_layer(admin_page)
    expect(admin_page.locator(".structure-box")).to_have_count(5)
    fold_all = admin_page.locator("[data-fold-all]")
    fold_all.click()
    expect(admin_page.locator(".structure-box")).to_have_count(3)
    expect(admin_page.locator(".structure-level")).to_have_text(["Top", "Level 2"])
    expect(fold_all).to_have_text("Unfold all")
    expect(admin_page.get_by_role("button", name="Unfold Second", exact=True)).to_have_text("+2")
    fold_all.click()
    expect(admin_page.locator(".structure-box")).to_have_count(5)
    expect(fold_all).to_have_text("Fold all")
    clean(admin_page)


def test_search_unfolds_and_marks_matches(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    open_layer(admin_page)
    admin_page.locator("[data-fold-all]").click()
    expect(box(admin_page, "London Swaps")).to_have_count(0)
    admin_page.get_by_label("Find a team", exact=True).fill("SWAPS")
    expect(box(admin_page, "London Swaps")).to_have_class(re.compile(r"\bis-match\b"))
    stage = admin_page.locator("[data-structure-stage]")
    expect(stage).to_have_class(re.compile(r"\bis-searching\b"))
    expect(box(admin_page, "Global Markets")).not_to_have_class(re.compile(r"\bis-match\b"))
    assert box(admin_page, "Global Markets").evaluate("el => getComputedStyle(el).opacity") == "0.35"
    admin_page.get_by_label("Find a team", exact=True).fill("")
    expect(stage).not_to_have_class(re.compile(r"\bis-searching\b"))
    expect(admin_page.locator(".structure-box.is-match")).to_have_count(0)
    clean(admin_page)


def test_a_folded_other_parent_draws_no_dotted_line(admin_page, live_server, team_factory):
    alpha, group = team_factory("Alpha"), team_factory("Group")
    beta = team_factory("Beta", parent=group)
    team_factory("Shared", parents=(alpha, beta), main=alpha)
    admin_page.goto(f"{live_server}/admin/teams/{alpha.id}")
    open_layer(admin_page)
    expect(admin_page.locator("path.structure-line.is-dotted")).to_have_count(1)
    admin_page.get_by_role("button", name="Fold Group").click()
    expect(box(admin_page, "Beta")).to_have_count(0)
    expect(admin_page.locator("path.structure-line.is-dotted")).to_have_count(0)
    expect(admin_page.locator("circle.structure-line-end")).to_have_count(0)
    box(admin_page, "Shared").hover()  # lighting with the other higher team hidden
    admin_page.get_by_role("button", name="Unfold Group").click()
    expect(admin_page.locator("path.structure-line.is-dotted")).to_have_count(1)
    clean(admin_page)
