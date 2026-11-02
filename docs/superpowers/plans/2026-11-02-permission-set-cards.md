# Permission set cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the permission grid table on `/admin/permission-sets` with one card per set, led by a locked
Administrators card, keeping the same form and save action.

**Architecture:** Server-rendered Jinja cards inside the existing grid form (field names unchanged), with permission
groups defined beside `PERMISSIONS` and holder counts from one grouped query. A small progressive behaviour in
`admin.js` updates counts, "Changed" marks and the unsaved-changes note.

**Tech Stack:** Flask, SQLAlchemy 2, Jinja, plain ES5 JavaScript, Playwright browser tests, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-permission-set-cards-design.md`

## Global Constraints

- Strict CSP: no inline scripts, styles or event handlers; scripts load with `defer` from `static/`.
- Every control that needs JavaScript renders `hidden` and `admin.js` reveals it.
- CSRF field on every form; the grid form keeps `name="sets" value="<id>"` hidden fields and tick boxes
  `name="set-<id>" value="<permission>"`; POST endpoints, guards and Activity entries do not change.
- British formal copy, active voice, no contractions.
- No page-level horizontal scroll at 390 px or 1,440 px; light and dark from the existing CSS tokens only.
- Tick-box rows at least 44 px high; the whole row is the tick box's `<label>`.
- Exact copy:
  - Administrators card: name "Administrators", badge "Built in", line "Every permission, always. Only administrators
    change this screen.", count "7/7" (i.e. `len(PERMISSIONS)/len(PERMISSIONS)`), footer "Held by N people" /
    "Held by 1 person" linking to Users.
  - Set footer: "Held by 1 team and 2 people", "Held by 2 teams", "Held by 1 person", "Nobody holds this set yet.",
    link "Holders and details".
  - Empty description: "No description."
  - Card warning: "Holding both Manage users and Manage teams gives reach close to an administrator's."
  - Group headings: "People and teams", "Trackers", "Application".
  - New card: heading "New permission set", line "Create it here, tick its permissions on its card, then choose who
    holds it.", button "Create permission set"; header link "New permission set" to `#new-set`.
  - Save bar: "Administrators always hold every permission."; note without JavaScript "Saving applies every card at
    once."; with JavaScript "No unsaved changes" / "Unsaved changes in 1 set" / "Unsaved changes in N sets";
    button "Save permissions"; card badge "Changed".

## Review Focus

1. A set with a very long name or description: the card wraps its text and the page does not scroll sideways
   (Task 2 browser test uses a long name).
2. A failed create (duplicate name) re-renders the cards and keeps the typed name in the New permission set card
   (Task 1 test).
3. Inactive administrators are not counted on the Administrators card (Task 1 test).
4. No sets yet: the Administrators card and the New permission set card show, and no save bar does (Task 1 test).
5. Unticking back to the saved state clears the card's "Changed" mark and the note (Task 2 browser test).

---

### Task 1: Cards, groups and holder counts (server side)

**Files:**
- Modify: `tracker/auth/permissions.py` (add `PERMISSION_GROUPS` after `PERMISSIONS`)
- Modify: `tracker/permsets/views.py` (`_render_index` and a new `_holder_counts`)
- Modify: `tracker/templates/permsets/index.html` (rewrite the Permissions section and the New permission set section)
- Modify: `tracker/static/tracker.css` (replace the `.permission-grid` rules near line 908 with the card rules)
- Test: `tests/test_permission_sets.py`

**Interfaces:**
- Produces: `PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...]` in `tracker/auth/permissions.py`.
- Produces: `_holder_counts(set_ids: list[int]) -> dict[int, tuple[int, int]]` (set id → (teams, people)) in
  `tracker/permsets/views.py`; every requested id present, `(0, 0)` when no holders.
- Produces the markup contract Task 2 relies on:
  - `<form data-permission-cards ...>` (the existing grid form);
  - each set card `<article class="perm-card" data-set-card>` with a `<span data-count>` holding "n/7" and a
    `<span class="perm-card-badge" data-changed hidden>Changed</span>`;
  - the Administrators card `<article class="perm-card perm-card-builtin">` (no `data-set-card`, no inputs);
  - the note `<span class="settings-actions-note" data-dirty-note>Saving applies every card at once.</span>` inside a
    `.settings-actions` bar with the "Save permissions" submit button.
- Template data: `sets`, `held`, `permissions`, `groups=PERMISSION_GROUPS`, `holder_counts`, `admin_count`
  (active administrators), `form`, `errors`.

- [ ] **Step 1: Write the failing tests** in `tests/test_permission_sets.py`

```python
from tracker.auth.permissions import PERMISSION_GROUPS

def cards(page: str) -> list[str]:
    return page.split("data-set-card")[1:]

def test_permission_groups_cover_every_permission_once_in_order():
    assert [name for name, _ in PERMISSION_GROUPS] == ["People and teams", "Trackers", "Application"]
    assert [p for _, keys in PERMISSION_GROUPS for p in keys] == list(PERMISSIONS)

def test_index_shows_the_locked_administrators_card_then_a_card_per_set(client, logged_in_admin, db):
    pmo = make_set(db, "PMO", ["view_activity"])
    make_set(db, "Auditors", [])
    page = text_of(client.get("/admin/permission-sets"))
    assert page.index("Administrators") < page.index("Auditors") < page.index("PMO")
    assert "Built in" in page and "7/7" in page and "Every permission, always." in page
    assert "1/7" in page and "0/7" in page and "No description." in page
    assert 'aria-label="View activity for PMO"' in page and f'name="set-{pmo.id}"' in page
    assert "People and teams" in page and "Application" in page
    assert len(cards(page)) == 2 and "data-permission-cards" in page
    assert "Saving applies every card at once." in page

def test_cards_count_holders(client, logged_in_admin, db, user_factory, team_factory, give_set):
    both = give_set(["view_activity"], team=team_factory(name="Ops"), name="Both")
    give_set(["view_activity"], user=user_factory(), name="Solo")
    db.add(PermissionSetHolder(set_id=both.id, user_id=user_factory().id))
    db.add(PermissionSetHolder(set_id=both.id, user_id=user_factory().id))
    db.commit()
    make_set(db, "Empty", [])
    user_factory(is_admin=True)
    user_factory(is_admin=True, status="disabled")
    page = text_of(client.get("/admin/permission-sets"))
    assert "Held by 1 team and 2 people" in page and "Held by 1 person" in page
    assert "Nobody holds this set yet." in page
    assert "Held by 2 people" in page  # the signed-in administrator and one more active one

def test_card_warns_only_where_a_set_grants_users_and_teams(client, logged_in_admin, db):
    make_set(db, "Both", ["manage_users", "manage_teams"])
    make_set(db, "One", ["manage_users"])
    page = text_of(client.get("/admin/permission-sets"))
    warning = "Holding both Manage users and Manage teams gives reach close to an administrator's."
    both, one = cards(page)
    assert warning in both and warning not in one

def test_no_sets_still_shows_administrators_and_new_set_cards(client, logged_in_admin):
    page = text_of(client.get("/admin/permission-sets"))
    assert "Administrators" in page and 'id="new-set"' in page and 'href="#new-set"' in page
    assert "Save permissions" not in page

def test_failed_create_keeps_the_typed_name_in_the_new_set_card(client, logged_in_admin, db):
    make_set(db, "PMO", [])
    response = post(client, "/admin/permission-sets", {"name": "pmo", "description": "Again"})
    page = text_of(response)
    assert response.status_code == 400 and 'id="new-set"' in page and 'value="pmo"' in page
    assert len(cards(page)) == 1
```

Check the `give_set` and `user_factory` fixture signatures in `tests/conftest.py` (status keyword, holder kinds) and
adjust only the fixture calls, never the assertions. Check the disabled-status spelling against `User.status`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_permission_sets.py -q`
Expected: the new tests FAIL (import error for `PERMISSION_GROUPS` first); the existing ones still pass.

- [ ] **Step 3: Implement**
  - `PERMISSION_GROUPS` with the groups and order in Global Constraints and the spec (People and teams: manage_users,
    manage_teams; Trackers: create_trackers, import_workbooks, view_all_trackers; Application: manage_email_settings,
    view_activity).
  - `_holder_counts`: one `select(set_id, count(team_id), count(user_id)).group_by(set_id)` over
    `PermissionSetHolder`; `admin_count`: active users with `is_admin`.
  - Template: page header (h1, lede keeping the existing two sentences about sets and the Manage users / Manage teams
    sentence, the "New permission set" link styled as a primary button with `icon('plus')`), the error alert as today,
    then a `.perm-cards` grid: the Administrators card (`icon('admin')` on a navy square, `icon('lock')` on each
    row with an accessible name "Always held"), the set cards inside the grid form (`icon('key')` on a tinted square;
    rows per group; warning with `icon('warning')`; footer text and link to `permsets.view` with `icon('chevron-right')`),
    and the dashed `section#new-set` card holding the existing create form fields. The form wraps only the set cards
    and the save bar; the Administrators card and New card sit in the same CSS grid (use `display: contents` on the
    form, or place the form around the whole grid and give the create form its own element outside it — the create
    form must not nest inside the grid form).
  - CSS: card, header, group heading, row (min-height 44px, hover tint), warning, footer, dashed new card,
    `.perm-card.is-changed` (primary border and ring) using only existing tokens; grid
    `repeat(auto-fill, minmax(min(100%, 330px), 1fr))`; remove the `.permission-grid` rules.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_permission_sets.py tests/test_permissions.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tracker/auth/permissions.py tracker/permsets/views.py tracker/templates/permsets/index.html tracker/static/tracker.css tests/test_permission_sets.py
git commit -m "feat: permission sets as cards, led by a locked Administrators card"
```

### Task 2: Live counts, "Changed" marks and the save note

**Files:**
- Modify: `tracker/static/admin.js` (one new behaviour block)
- Modify: `tracker/templates/permsets/index.html` (load `admin.js` with `defer`, as `teams/index.html` does)
- Test: create `tests/test_permsets_browser.py`

**Interfaces:**
- Consumes: Task 1's markup contract.
- Behaviour: for `form[data-permission-cards]`, remember each tick box's starting state; on `change`, for each
  `article[data-set-card]` set `[data-count]` to "<ticked>/<total>", toggle `.is-changed` and the badge's `hidden`
  when any of its boxes differs from the start; set `[data-dirty-note]` text per Global Constraints and toggle its
  `is-dirty` class.

- [ ] **Step 1: Write the failing browser tests** (`pytestmark = pytest.mark.browser`, patterns from
  `tests/test_users_browser.py`: `browser_sign_in`, `RECORDER`, `window.__csp`, `window.__errors`)

```python
def test_ticking_updates_the_card_and_the_note(page, live_server, user_factory, give_set):
    give_set(["view_activity"], name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    card = page.locator("article[data-set-card]", has_text="PMO")
    note = page.locator("[data-dirty-note]")
    expect(note).to_have_text("No unsaved changes")
    page.get_by_label("Manage users for PMO").check()
    expect(card.locator("[data-count]")).to_have_text("2/7")
    expect(card).to_have_class(re.compile(r"\bis-changed\b"))
    expect(card.get_by_text("Changed")).to_be_visible()
    expect(note).to_have_text("Unsaved changes in 1 set")
    page.get_by_label("Manage users for PMO").uncheck()
    expect(card.locator("[data-count]")).to_have_text("1/7")
    expect(card.get_by_text("Changed")).to_be_hidden()
    expect(note).to_have_text("No unsaved changes")
    page.get_by_label("Create trackers for PMO").check()
    page.get_by_role("button", name="Save permissions").click()
    expect(page.get_by_text("Saved the permissions.")).to_be_visible()
    expect(page.locator("article[data-set-card]", has_text="PMO").locator("[data-count]")).to_have_text("2/7")

@pytest.mark.parametrize("size", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
def test_cards_fit_without_page_scroll(page, live_server, user_factory, give_set, size):
    give_set(["manage_users", "manage_teams"], name="Programme management office and delivery assurance " * 3)
    give_set(["view_activity"], name="PMO")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []
```

If `give_set` refuses a name over 100 characters, cut the long name to 100 characters.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_permsets_browser.py -q -m browser`
Expected: the first test FAILS on the note text; the fit test may pass already.

- [ ] **Step 3: Implement the `admin.js` block and load the script** (ES5, the file's `each` helper, a comment line
  in the file's style naming the markup it drives).

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_permsets_browser.py tests/test_permission_sets.py tests/test_teams_browser.py -q`
Expected: all PASS.

- [ ] **Step 5: Full checks and commit**

Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`
Expected: all pass, ruff clean.

```bash
git add tracker/static/admin.js tracker/templates/permsets/index.html tests/test_permsets_browser.py
git commit -m "feat: permission cards update their counts and the save note as you tick"
```
