# Regions, locations and business lines (stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Administrators keep lists of regions, locations and business lines; every team gets a location (and so a
region), every tracker a business line and one or more regions; the home page filters by both and cards and reports
show them.

**Architecture:** Three new tables (`regions`, `locations`, `business_lines`), one link table (`tracker_regions`) and two
nullable foreign keys (`teams.location_id`, `trackers.business_line_id`) in migration 0004. A new `tracker/lists/`
package holds the database helpers (`catalogue.py`: choices, parsing, labels) and the administrator screens
(`views.py`). Teams, trackers, the importer, home and report read the helpers; nothing in access control changes in
this stage.

**Tech Stack:** Flask 3.1, SQLAlchemy 2, Jinja, Postgres, Alembic, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-02-regions-locations-business-lines-design.md` (sections 1, 2, 3 and 6).

## Global Constraints

- Strict CSP (no inline script or style), CSRF on every POST (`csrf_field(csrf_token())`), works without JavaScript,
  light and dark themes, no page-level horizontal scroll at 390 px, Alembic migration for every schema change.
- British formal copy in the active voice, no contractions.
- Administrator-only management of the lists, "written so that each can later become a permission in the permission
  sets without restructuring": every list route uses one decorator alias, `manage_lists_required`, defined once in
  `tracker/lists/views.py` as `admin_required`; the nav shows the screens when `current_user.is_admin`.
- Access stays fail-closed: anything unset grants nothing (this stage grants nothing at all).
- Every change commits with its Activity entry in one transaction (`tracker.audit.record`), as the teams screens do.
- Entries in use are retired, never deleted; a retired entry is not offered for new choices but keeps showing, and
  keeps validating, wherever it is already used. An entry nothing uses can be deleted.
- Seeded business lines, exactly: `Tradition brokerage`, `TraditionData`. Regions and locations start empty.
- Existing teams and trackers show "Not set" ("Region not set" on the Teams screen); the next save requires both values.
- Commit identity: `git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit`, message ending
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests: `WT=$PWD ../tools/acc-test.sh <pytest args>`, run from the worktree with the sandbox disabled (database `tracker_test_design`); `ruff check` and
  `ruff format --check` clean.

## Review Focus

1. A team or tracker that uses an entry which is later retired is saved again unchanged: the save must succeed and the
   retired entry must stay selected (tested in Tasks 4 and 5).
2. A location from a different region is posted with a region (tampered form, or no JavaScript to narrow the list): it
   is refused with "The location is not in the chosen region." and nothing is saved (Task 2 and Task 4).
3. A location moved to another region: every team at that location shows the new region at once, and the Activity
   entry records how many teams moved (Task 3).
4. Deleting an entry in use (a region with locations or trackers, a location with teams, a business line with
   trackers) is refused with a message that says to retire it; nothing is deleted (Task 3).
5. Saving the settings of a tracker created before this change without choosing a business line or region is refused
   with both messages, and none of the other submitted changes is saved (Task 5).

---

### Task 1: Schema and migration 0004

**Files:**
- Modify: `tracker/models.py`
- Create: `migrations/versions/0004_regions_locations_business_lines.py`
- Modify: `tests/test_migration_matches_models.py`
- Create: `tests/test_migration_0004.py`

**Interfaces:**
- Produces (in `tracker.models`):
  - `Region`: table `regions`; `id`, `code: str` (short name, "EMEA"), `name: str` (full name), `retired: bool`
    (default false), `created_at`. Unique indexes `uq_regions_code_lower` on `lower(code)`, `uq_regions_name_lower` on
    `lower(name)`.
  - `Location`: table `locations`; `id`, `region_id` (FK `regions.id`, `ondelete="RESTRICT"`, not null), `city: str`,
    `country: str`, `retired: bool`, `created_at`. Unique index `uq_locations_city_country_lower` on
    `(lower(city), lower(country))`; index `ix_locations_region_id`.
  - `BusinessLine`: table `business_lines`; `id`, `name: str`, `retired: bool`, `created_at`. Unique index
    `uq_business_lines_name_lower` on `lower(name)`.
  - `TrackerRegion`: table `tracker_regions`; `tracker_id` (FK trackers, `CASCADE`, PK), `region_id` (FK regions,
    `RESTRICT`, PK). Index `ix_tracker_regions_region_id`.
  - `Team.location_id: int | None` (FK `locations.id`, `RESTRICT`), index `ix_teams_location_id`.
  - `Tracker.business_line_id: int | None` (FK `business_lines.id`, `RESTRICT`), index `ix_trackers_business_line_id`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_migration_matches_models.py` add:

```python
def test_migration_creates_list_indexes_and_seeds_business_lines():
    sql = _offline_sql()
    assert "CREATE UNIQUE INDEX uq_regions_code_lower ON regions (lower(code))" in sql
    assert "CREATE UNIQUE INDEX uq_regions_name_lower ON regions (lower(name))" in sql
    assert "CREATE UNIQUE INDEX uq_locations_city_country_lower ON locations (lower(city), lower(country))" in sql
    assert "CREATE UNIQUE INDEX uq_business_lines_name_lower ON business_lines (lower(name))" in sql
    assert "'Tradition brokerage'" in sql and "'TraditionData'" in sql
```

Create `tests/test_migration_0004.py` in the style of `tests/test_migration_0003.py` (fixture `at_revision_0003`
downgrading to `"0003"` and upgrading to head in `finally`):

```python
def test_upgrade_keeps_teams_and_trackers_unset_and_seeds_two_business_lines(db, at_revision_0003):
    team_id = db.execute(text("INSERT INTO teams (name) VALUES ('Desktop') RETURNING id")).scalar_one()
    tracker_id = _insert_tracker(db, "A")  # copy the helper from test_migration_0003
    db.commit()
    command.upgrade(alembic_config(), "head")
    assert db.get(Team, team_id).location_id is None
    assert db.get(Tracker, tracker_id).business_line_id is None
    assert db.scalar(select(func.count()).select_from(TrackerRegion)) == 0
    assert sorted(db.scalars(select(BusinessLine.name))) == ["Tradition brokerage", "TraditionData"]
    assert db.scalar(select(func.count()).select_from(Region)) == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_migration_matches_models.py tests/test_migration_0004.py -q`
Expected: FAIL (`ImportError` for `BusinessLine`, and the offline SQL lacks the indexes).

- [ ] **Step 3: Add the models and migration 0004**

Models as in Interfaces, in the existing style (`Identity()` ids, `_now()`, `Index(...)` after the class for the
`lower()` indexes). Migration: revision `"0004"`, down `"0003"`, hand-written like 0003 with `op.f()` names; the seed
is `op.bulk_insert` (or `op.execute` INSERT) of the two names; `downgrade` drops everything in reverse order.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_migration_matches_models.py tests/test_migration_0004.py tests/test_migration_0003.py tests/test_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** — `feat: regions, locations and business lines tables (migration 0004)`

---

### Task 2: List helpers (`tracker/lists/catalogue.py`)

**Files:**
- Create: `tracker/lists/__init__.py` (Blueprint `lists`, `url_prefix="/admin"`, imports `views` like
  `tracker/permsets/__init__.py`; `views.py` may be an empty module until Task 3)
- Create: `tracker/lists/catalogue.py`
- Modify: `tracker/naming.py` (generalise `name_error`)
- Modify: `tests/conftest.py` (fixtures)
- Test: `tests/test_lists_catalogue.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces (in `tracker.lists.catalogue`; no Flask imports):
  - Messages: `LOCATION_REQUIRED = "Choose a region and a location."`,
    `LOCATION_CHOICE_ERROR = "Choose a location from the list."`,
    `LOCATION_REGION_MISMATCH = "The location is not in the chosen region."`,
    `BUSINESS_LINE_REQUIRED = "Choose a business line."`,
    `BUSINESS_LINE_CHOICE_ERROR = "Choose a business line from the list."`,
    `REGIONS_REQUIRED = "Tick at least one region."`, `REGIONS_CHOICE_ERROR = "Choose regions from the list."`.
  - `location_label(city: str, country: str) -> str` → `"Geneva, Switzerland"`.
  - `class Place(NamedTuple)`: `location_id: int`, `location: str` (the label), `region_id: int`, `region_code: str`.
  - `team_places(session) -> dict[int, Place]` — team id to its place, for teams with a location only.
  - `class RegionOption(NamedTuple)`: `id: int`, `code: str`, `name: str`, `retired: bool`,
    `locations: list[tuple[int, str, bool]]` (location id, label, retired).
  - `location_choices(session, keep_id: int | None = None) -> list[RegionOption]` — regions by `lower(code)`, each
    with its locations by label; retired regions and locations are left out unless they hold `keep_id`.
  - `region_choices(session, keep_ids: Collection[int] = ()) -> list[RegionOption]` — the same regions, `locations`
    empty; retired ones only when in `keep_ids`.
  - `business_line_choices(session, keep_id: int | None = None) -> list[tuple[int, str, bool]]` by `lower(name)`.
  - `parse_location(session, region_text: str | None, location_text: str | None, current_id: int | None) ->
    tuple[Location | None, str | None]` — either value empty gives `LOCATION_REQUIRED`; an unknown id, or a retired
    location other than `current_id` (or one in a retired region, other than `current_id`), gives
    `LOCATION_CHOICE_ERROR`; a location whose `region_id` differs from the chosen region gives
    `LOCATION_REGION_MISMATCH`.
  - `parse_business_line(session, text: str | None, current_id: int | None) -> tuple[BusinessLine | None, str | None]`
    with the same retired rule.
  - `parse_regions(session, texts: list[str], current_ids: Collection[int]) -> tuple[list[Region], str | None]` —
    none ticked gives `REGIONS_REQUIRED`; any unknown id, or a retired region not in `current_ids`, gives
    `REGIONS_CHOICE_ERROR`; duplicates collapse; result ordered by `lower(code)`.
  - `class TrackerLabels(NamedTuple)`: `business_line: str | None`, `regions: list[str]` (codes by `lower(code)`).
  - `tracker_labels(session, tracker_ids: Collection[int]) -> dict[int, TrackerLabels]` — every requested id present,
    `TrackerLabels(None, [])` when unset.
  - `tracker_region_ids(session, tracker_id: int) -> set[int]`.
  - `set_tracker_regions(session, tracker_id: int, region_ids: Collection[int]) -> None` (replace; caller commits).
- Produces (in `tracker.naming`): `name_error(session, model, name, noun, exclude_id=None, column=None)` — `column`
  defaults to `model.name`; the message noun is unchanged. Existing callers are untouched.
- Produces (in `tests/conftest.py`): fixtures `region_factory(code="EMEA", name=None, retired=False) -> Region`
  (name defaults to `f"{code} region"`), `location_factory(region, city="Geneva", country="Switzerland",
  retired=False) -> Location`, `business_line_factory(name="Tradition brokerage", retired=False) -> BusinessLine`.

- [ ] **Step 1: Write the failing tests** in `tests/test_lists_catalogue.py`:

```python
def test_parse_location_refuses_a_location_from_another_region(db, region_factory, location_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    geneva = location_factory(emea)
    assert parse_location(db, str(apac.id), str(geneva.id), None) == (None, LOCATION_REGION_MISMATCH)
    assert parse_location(db, str(emea.id), str(geneva.id), None) == (geneva, None)
    assert parse_location(db, "", str(geneva.id), None) == (None, LOCATION_REQUIRED)
    assert parse_location(db, str(emea.id), "99999999999", None) == (None, LOCATION_CHOICE_ERROR)

def test_a_retired_location_is_accepted_only_where_it_is_already_used(db, region_factory, location_factory):
    emea = region_factory("EMEA")
    old = location_factory(emea, city="Zurich", retired=True)
    assert parse_location(db, str(emea.id), str(old.id), None) == (None, LOCATION_CHOICE_ERROR)
    assert parse_location(db, str(emea.id), str(old.id), old.id) == (old, None)
    assert [o.code for o in location_choices(db)] == ["EMEA"] and location_choices(db)[0].locations == []
    assert location_choices(db, keep_id=old.id)[0].locations == [(old.id, "Zurich, Switzerland", True)]

def test_parse_regions_requires_one_and_refuses_unknown_and_retired(db, region_factory):
    emea, gone = region_factory("EMEA"), region_factory("LATAM", retired=True)
    assert parse_regions(db, [], ()) == ([], REGIONS_REQUIRED)
    assert parse_regions(db, [str(emea.id), "x"], ()) == ([], REGIONS_CHOICE_ERROR)
    assert parse_regions(db, [str(gone.id)], ()) == ([], REGIONS_CHOICE_ERROR)
    assert parse_regions(db, [str(gone.id), str(emea.id), str(emea.id)], {gone.id}) == ([emea, gone], None)

def test_parse_business_line(db, business_line_factory):
    line, old = business_line_factory(), business_line_factory("Old line", retired=True)
    assert parse_business_line(db, "", None) == (None, BUSINESS_LINE_REQUIRED)
    assert parse_business_line(db, str(old.id), None) == (None, BUSINESS_LINE_CHOICE_ERROR)
    assert parse_business_line(db, str(old.id), old.id) == (old, None)
    assert parse_business_line(db, str(line.id), None) == (line, None)

def test_tracker_labels_and_team_places(db, tracker_factory, team_factory, region_factory, location_factory,
                                        business_line_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    team = team_factory("Desktop", location_id=location_factory(emea).id)
    unset = tracker_factory(name="Unset")
    labelled = tracker_factory(name="Labelled", business_line_id=business_line_factory().id)
    set_tracker_regions(db, labelled.id, [emea.id, apac.id]); db.commit()
    assert tracker_labels(db, [unset.id, labelled.id]) == {
        unset.id: TrackerLabels(None, []), labelled.id: TrackerLabels("Tradition brokerage", ["APAC", "EMEA"])}
    assert team_places(db)[team.id].location == "Geneva, Switzerland"
    assert team_places(db)[team.id].region_code == "EMEA"
```

- [ ] **Step 2: Run to verify they fail**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_lists_catalogue.py -q`
Expected: FAIL (module `tracker.lists.catalogue` not found).

- [ ] **Step 3: Implement** the Interfaces above; ids parsed with `tracker.ids.parse_id`.
- [ ] **Step 4: Run to verify they pass** — same command; Expected: PASS. Also `tests/test_teams.py tests/test_permission_sets.py -q` still PASS (the `name_error` change).
- [ ] **Step 5: Commit** — `feat: helpers for choosing regions, locations and business lines`

---

### Task 3: Administration screens for the lists

**Files:**
- Create: `tracker/lists/views.py`
- Create: `tracker/templates/lists/regions.html`, `tracker/templates/lists/business_lines.html`
- Modify: `tracker/app.py` (register `lists_bp`), `tracker/templates/base.html` (nav), `tracker/templates/macros.html`
  (icons `globe` and `briefcase`, 24×24 stroke icons like the existing ones), `tracker/activity/labels.py`,
  `tracker/static/tracker.css` (only what the new screens need)
- Test: `tests/test_lists_admin.py`

**Interfaces:**
- Consumes: Task 1 models; Task 2 `location_label`, `name_error(column=...)`.
- Produces: endpoints (all `@manage_lists_required`, where `manage_lists_required = admin_required`):
  - `GET /admin/regions` → `lists.regions`: page "Regions and locations". One section per region (code, full name, a
    "Retired" badge, its locations with "Retired" badges and the number of teams using each), forms to add a region and
    to add a location to a region, and per entry an edit form (details element) with Save, Retire/Restore and, only when
    unused, Delete.
  - `POST /admin/regions` → `lists.create_region` (fields `code`, `name`).
  - `POST /admin/regions/<int:region_id>` → `lists.update_region` (`action` = `save` | `retire` | `restore` | `delete`;
    `save` takes `code`, `name`).
  - `POST /admin/regions/<int:region_id>/locations` → `lists.create_location` (`city`, `country`).
  - `POST /admin/locations/<int:location_id>` → `lists.update_location` (`action` as above; `save` takes `city`,
    `country`, `region_id`).
  - `GET /admin/business-lines` → `lists.business_lines`; `POST /admin/business-lines` → `lists.create_business_line`
    (`name`); `POST /admin/business-lines/<int:line_id>` → `lists.update_business_line` (`action`; `save` takes `name`).
  - Validation: region code required, at most 20 characters; region name, city, country and business line name
    required, at most 100 characters; uniqueness ignoring case via `name_error` (region code and name, business line
    name) and for city plus country together (`"A location with that city and country already exists."`); a
    concurrent duplicate's `IntegrityError` gives the same message, as `teams.create` does. Errors re-render the page
    with status 400 and the form alert, like `teams/index.html`.
  - Delete refusals (400, nothing deleted): `"This region has locations or trackers, so it can only be retired."`,
    `"Teams use this location, so it can only be retired."`, `"Trackers use this business line, so it can only be
    retired."`.
  - Activity actions (entity `region` / `location` / `business_line`, `entity_id` the id, `tracker_id=None`) and labels:
    `region_created` "Region added", `region_changed` "Region changed", `region_retired` "Region retired",
    `region_restored` "Region restored", `region_deleted` "Region deleted", and the same five for `location_*`
    ("Location …") and `business_line_*` ("Business line …"). Created/deleted detail names the entry
    (`{"region": "EMEA"}`, `{"location": "Geneva, Switzerland", "region": "EMEA"}`, `{"business_line": name}`);
    changed detail is `change(before, after)` of the changed fields only; a save that changes nothing flashes
    `NO_CHANGES_MESSAGE` and writes nothing. A location whose region changes also gets `"teams": <count>` in its
    detail.
  - The location edit form's help text says how many teams use it and that changing the region moves them:
    `"Used by 3 teams. Changing the region moves them to it."` (singular "1 team"; omitted at 0).
  - Nav: under Administration, after Teams, `Regions and locations` (`globe`, `current_page="regions"`) and
    `Business lines` (`briefcase`, `current_page="business_lines"`) when `current_user.is_admin`; include `show_lists`
    in the heading condition.

- [ ] **Step 1: Write the failing tests** in `tests/test_lists_admin.py`, among them:

```python
def test_lists_are_for_administrators_only(client, logged_in_user, give_set):
    give_set(["manage_teams", "manage_users"], user=logged_in_user)
    for url in ("/admin/regions", "/admin/business-lines"):
        assert client.get(url).status_code == 403
    assert post(client, "/admin/regions", {"code": "EMEA", "name": "Europe"}).status_code == 403

def test_admin_adds_a_region_and_a_location_and_both_are_logged(client, logged_in_admin, db): ...
    # POST /admin/regions {"code": " EMEA ", "name": "Europe, Middle East and Africa"} → 302; Region code "EMEA"
    # POST /admin/regions/<id>/locations {"city": "Geneva", "country": "Switzerland"} → 302
    # AuditLog actions == ["region_created", "location_created"]; second detail == {"location": "Geneva, Switzerland", "region": "EMEA"}

def test_duplicate_names_are_refused_ignoring_case(...):  # code "emea", name, and city+country "geneva"/"SWITZERLAND" → 400 with the messages

def test_moving_a_location_moves_its_teams_and_logs_the_count(client, logged_in_admin, db, region_factory,
                                                               location_factory, team_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    place = location_factory(emea)
    team_factory("A", location_id=place.id); team_factory("B", location_id=place.id)
    page = client.get("/admin/regions").get_data(as_text=True)
    assert "Used by 2 teams. Changing the region moves them to it." in page
    post(client, f"/admin/locations/{place.id}", {"action": "save", "city": "Geneva", "country": "Switzerland",
                                                  "region_id": str(apac.id)})
    assert {p.region_code for p in team_places(db).values()} == {"APAC"}
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "location_changed")).one()
    assert entry.detail["teams"] == 2

def test_entries_in_use_cannot_be_deleted_only_retired(...):
    # region with a location → delete 400 with the region message; location with a team → 400; business line used by
    # a tracker → 400; each still exists. Retire each → retired True, actions *_retired. An unused region deletes (302).

def test_retired_entries_show_a_badge_and_restore(...):  # page shows "Retired"; action=restore → retired False, *_restored

def test_saving_unchanged_writes_no_entry(...)  # NO_CHANGES_MESSAGE flashed, no AuditLog row

def test_nav_shows_the_lists_to_administrators_only(...)  # "Regions and locations" and "Business lines" links
```

Write each test fully with the exact messages from Interfaces.

- [ ] **Step 2: Run to verify they fail**

Run: `WT=$PWD ../tools/acc-test.sh tests/test_lists_admin.py -q`
Expected: FAIL (404 for `/admin/regions`).

- [ ] **Step 3: Implement** the views, templates, nav, icons and labels. Use `"Regions and locations"` and
`"Business lines"` as the `h1`s and page titles; the lede of the regions page: `"Teams are placed at a location, and
each location belongs to one region. Trackers say which regions they cover."`; of the business lines page:
`"Every tracker belongs to one business line."`.
- [ ] **Step 4: Run to verify they pass** — same command plus `tests/test_activity_labels.py tests/test_templates.py -q`; Expected: PASS.
- [ ] **Step 5: Commit** — `feat: administration screens for regions, locations and business lines`

---

### Task 4: Teams have a region and a location

**Files:**
- Modify: `tracker/teams/views.py` (`create`, `rename`, `_render_index`, `_render_team`, `_tree_context`)
- Modify: `tracker/templates/teams/index.html`, `tracker/templates/teams/team.html`, `tracker/templates/teams/_tree.html`
- Create: `tracker/templates/teams/_place_fields.html` (the two selects, shared by both forms)
- Modify: `tracker/static/admin.js` (narrowing), `tracker/static/tracker.css`, `tracker/activity/labels.py`
- Modify: `tests/test_teams.py`, `tests/test_teams_browser.py` (existing posts gain the place fields)
- Test: `tests/test_team_places.py`

**Interfaces:**
- Consumes: Task 2 `parse_location`, `location_choices`, `team_places`, `Place`; fixtures.
- Produces:
  - Form fields `region_id` and `location_id` on New team and Edit details. The Location select lists every offered
    location in `<optgroup label="<code> – <name>">` groups (works without JavaScript); `admin.js` hides the optgroups
    of other regions when `select[data-region-select]` changes and clears a location that no longer fits. Retired
    choices that are kept show `" (retired)"` after their label.
  - `create` and `rename` require a place via `parse_location(db, form["region_id"], form["location_id"], current)`
    (`current` = the team's `location_id` on rename, `None` on create); the error joins the existing error list.
  - `team_created` detail gains `"location": "Geneva, Switzerland (EMEA)"`. On rename a location change is one more
    changed field, `"location"`, in the existing `change(before, after)` detail, with `None` for unset. The label of
    `team_renamed` becomes `"Team details changed"`.
  - Tree (`_tree.html`): each node shows `<span class="team-place">EMEA · Geneva</span>`, or
    `<span class="team-place is-unset">Region not set</span>`; `_tree_context` adds `places=team_places(db)`.
  - Team page header shows `"EMEA · Geneva, Switzerland"` or `"Region not set"` under the name.

- [ ] **Step 1: Write the failing tests** in `tests/test_team_places.py`:

```python
def test_a_new_team_needs_a_region_and_a_location(client, logged_in_admin, db, region_factory, location_factory):
    emea = region_factory("EMEA"); geneva = location_factory(emea)
    page = post(client, "/admin/teams", {"name": "Desktop"})
    assert page.status_code == 400 and "Choose a region and a location." in page.get_data(as_text=True)
    assert post(client, "/admin/teams", {"name": "Desktop", "region_id": str(emea.id),
                                         "location_id": str(geneva.id)}).status_code == 302
    team = db.scalars(select(Team)).one()
    assert team.location_id == geneva.id
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "team_created")).one()
    assert entry.detail["location"] == "Geneva, Switzerland (EMEA)"

def test_a_location_from_another_region_is_refused(...)  # 400 with LOCATION_REGION_MISMATCH, no team

def test_an_existing_team_shows_region_not_set_and_its_next_save_needs_a_place(client, logged_in_admin, db,
        team_factory, region_factory, location_factory):
    team = team_factory("Desktop")
    assert "Region not set" in client.get("/admin/teams").get_data(as_text=True)
    page = post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktop", "description": ""})
    assert page.status_code == 400 and "Choose a region and a location." in page.get_data(as_text=True)

def test_saving_a_team_at_a_retired_location_keeps_it(client, logged_in_admin, db, team_factory, region_factory,
                                                     location_factory):
    emea = region_factory("EMEA"); old = location_factory(emea, retired=True)
    team = team_factory("Desktop", location_id=old.id)
    page = client.get(f"/admin/teams/{team.id}").get_data(as_text=True)
    assert "Geneva, Switzerland (retired)" in page
    response = post(client, f"/admin/teams/{team.id}/rename", {"name": "Desktop 2", "description": "",
                    "region_id": str(emea.id), "location_id": str(old.id)})
    assert response.status_code == 302 and db.get(Team, team.id).location_id == old.id

def test_tree_and_team_page_show_the_place(...)  # "EMEA · Geneva" in the tree; "EMEA · Geneva, Switzerland" on the page

def test_location_change_is_logged_as_a_details_change(...)  # team_renamed detail before/after include "location"
```

- [ ] **Step 2: Run to verify they fail** — `WT=$PWD ../tools/acc-test.sh tests/test_team_places.py -q`; Expected: FAIL.
- [ ] **Step 3: Implement**; then update the existing posts to `/admin/teams` and `/admin/teams/<id>/rename` in
  `tests/test_teams.py` and the browser flows in `tests/test_teams_browser.py` to send a place (a module fixture that
  creates one region and location and returns the two form fields). A test whose point is another error keeps
  asserting that error.
- [ ] **Step 4: Run to verify they pass** — `WT=$PWD ../tools/acc-test.sh tests/test_team_places.py tests/test_teams.py tests/test_teams_browser.py tests/test_team_tree.py tests/test_activity_labels.py -q`; Expected: PASS.
- [ ] **Step 5: Commit** — `feat: teams have a region and a location`

---

### Task 5: Trackers have a business line and regions

**Files:**
- Modify: `tracker/trackers/views.py` (`new`, `settings`, `_render_settings`, `_form_from_tracker`, `_defaults_form`)
- Modify: `tracker/templates/trackers/_fields.html` (General section), `tracker/static/settings.js` or a new
  `tracker/static/tracker-new.js` (pre-tick), `tracker/static/tracker.css`
- Modify: `tracker/importer/views.py`, `tracker/importer/workbook.py` (`create_tracker_from_preview`),
  `tracker/templates/importer/confirm.html`
- Modify: `tests/test_trackers.py`, `tests/test_permissions.py`, `tests/test_tracker_teams.py`,
  `tests/test_settings_browser.py`, `tests/importer/` (existing posts gain the new fields)
- Test: `tests/test_tracker_labels.py`

**Interfaces:**
- Consumes: Task 2 `parse_business_line`, `parse_regions`, `business_line_choices`, `region_choices`,
  `tracker_region_ids`, `set_tracker_regions`, `team_places`.
- Produces:
  - Form fields `business_line_id` (select, first option `"Choose a business line"` with empty value) and
    `region_ids` (one checkbox per offered region, label `"<code> – <name>"`, `" (retired)"` for kept retired ones) in
    the General section of `_fields.html`, so New tracker and Settings both show them. Help text for Regions:
    `"Choose every region the tracker covers. In a later release, people given a region will see its trackers, so
    changing the regions changes who can see this tracker."` (my call: the spec's warning beside the tick boxes;
    worded for this stage, where no regional access exists yet).
  - New tracker: each team option carries `data-region="<region id>"` from `team_places`; the script ticks the
    chosen team's region when no region box has been touched yet. Without JavaScript nothing is pre-ticked.
  - `new` and `settings` POST validate both with the current values kept (`current_id=tracker.business_line_id`,
    `current_ids=tracker_region_ids(...)`; `None` / `()` on create), append the errors to the form errors, and save
    nothing when any error exists.
  - `create_tracker_from_preview(..., team_id=None, business_line_id: int | None = None, region_ids: Collection[int]
    = ())` sets both; the confirm view validates them with `parse_business_line` / `parse_regions` (create rules) and
    re-renders with the error (400). The CLI `import-workbook` passes neither (ruling: the CLI cannot ask; the tracker
    shows "Not set" until its next settings save).
  - Activity: `tracker_created` and `tracker_imported` detail gain `"business_line": name` and `"regions": [codes]`.
    A settings save that changes them adds `"business_line": [before, after]` and `"regions": [[codes before],
    [codes after]]` to the existing `settings_updated` detail (the legacy pair shape that action already uses;
    `None` / `[]` for unset).

- [ ] **Step 1: Write the failing tests** in `tests/test_tracker_labels.py`:

```python
def test_a_new_tracker_needs_a_business_line_and_a_region(client, logged_in_admin, db, region_factory,
                                                          business_line_factory):
    emea, line = region_factory("EMEA"), business_line_factory()
    page = post(client, "/trackers/new", SETTINGS)
    text = page.get_data(as_text=True)
    assert page.status_code == 400 and "Choose a business line." in text and "Tick at least one region." in text
    response = post(client, "/trackers/new", {**SETTINGS, "business_line_id": str(line.id), "region_ids": [str(emea.id)]})
    assert response.status_code == 302
    tracker = db.scalars(select(Tracker)).one()
    assert tracker_labels(db, [tracker.id])[tracker.id] == TrackerLabels("Tradition brokerage", ["EMEA"])
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "tracker_created")).one()
    assert entry.detail["business_line"] == "Tradition brokerage" and entry.detail["regions"] == ["EMEA"]

def test_an_old_tracker_shows_not_set_and_its_next_save_needs_both(client, logged_in_admin, db, tracker_factory,
                                                                  region_factory, business_line_factory):
    tracker = tracker_factory(name="Old")
    region_factory("EMEA"); business_line_factory()
    response = post(client, f"/trackers/{tracker.id}/settings", {**SETTINGS, "name": "Renamed"})
    assert response.status_code == 400
    assert db.get(Tracker, tracker.id).name == "Old"

def test_changing_regions_is_logged_before_and_after(...)  # settings_updated detail["regions"] == [["EMEA"], ["APAC", "EMEA"]]

def test_saving_with_a_retired_business_line_and_region_keeps_them(...)  # both retired, already set → 302, unchanged

def test_import_confirmation_asks_for_both(...)  # confirm without them → 400 with both messages; with them → labels set

def test_new_tracker_team_options_carry_their_region(...)  # 'data-region="<emea.id>"' on the team's option
```

`SETTINGS` is the dict from `tests/test_trackers.py` (import it).

- [ ] **Step 2: Run to verify they fail** — `WT=$PWD ../tools/acc-test.sh tests/test_tracker_labels.py -q`; Expected: FAIL.
- [ ] **Step 3: Implement**; then update the existing tests that create trackers through `/trackers/new`, save
  `/trackers/<id>/settings` or confirm an import, so they send a business line and a region (a conftest fixture
  `labels_form` that creates one of each and returns `{"business_line_id": ..., "region_ids": [...]}`). Browser
  settings flows choose them in the page.
- [ ] **Step 4: Run to verify they pass** — `WT=$PWD ../tools/acc-test.sh tests/test_tracker_labels.py tests/test_trackers.py tests/test_permissions.py tests/test_tracker_teams.py tests/test_settings_browser.py tests/importer/ tests/test_cli.py -q`; Expected: PASS.
- [ ] **Step 5: Commit** — `feat: trackers have a business line and regions`

---

### Task 6: Home filters, card and report labels

**Files:**
- Modify: `tracker/trackers/views.py` (`home`), `tracker/templates/home.html`, `tracker/static/home.js`,
  `tracker/static/tracker.css`
- Modify: `tracker/report/build.py` (`Report.labels`), `tracker/templates/report/_body.html`
- Test: `tests/test_home_labels.py`, and one browser test in `tests/test_home_labels_browser.py`

**Interfaces:**
- Consumes: Task 2 `tracker_labels`, `TrackerLabels`.
- Produces:
  - Each home card dict gains `"labels": TrackerLabels`. The card's subtitle line (`tracker-card-team`) reads the
    parts that are set, joined with `" · "`: team, business line, regions joined with `", "`; unset business line
    and regions show `"Business line not set"` and `"Regions not set"`. The list view's tracker cell shows the same in
    its `cell-sub`.
  - Each card and list row gets `data-line="<business line id or none>"` and
    `data-regions=" <id> <id> "` (space-padded, `" none "` when unset).
  - The home toolbar gains two selects, `Business line` (`data-home-line`) and `Region` (`data-home-region`), each
    with `All` (value `all`), the lines or regions used by the shown cards (by name / code), and `Not set` (value
    `none`) when any shown card lacks it. `home.js` combines them with the chip filter (AND); a region matches any
    tracker covering it. They follow the existing toolbar: hidden without JavaScript, when every card shows.
  - `Report` gains `labels: TrackerLabels`, filled in `build_report`; `_body.html` shows
    `<p class="report-meta">Tradition brokerage · EMEA, APAC</p>` under the title, with the same "not set" wording.

- [ ] **Step 1: Write the failing tests**:

```python
def test_cards_show_business_line_and_regions_and_carry_filter_data(client, logged_in_admin, db, tracker_factory,
        region_factory, business_line_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    labelled = tracker_factory(name="Labelled", business_line_id=business_line_factory().id)
    set_tracker_regions(db, labelled.id, [emea.id, apac.id]); db.commit()
    tracker_factory(name="Bare")
    page = client.get("/").get_data(as_text=True)
    assert "Tradition brokerage · APAC, EMEA" in page
    assert "Business line not set · Regions not set" in page
    assert f'data-regions=" {apac.id} {emea.id} "' in page or f'data-regions=" {emea.id} {apac.id} "' in page
    assert 'data-regions=" none "' in page

def test_report_header_shows_business_line_and_regions(...)  # GET /trackers/<id>/report → "Tradition brokerage · EMEA"

@pytest.mark.browser
def test_region_filter_shows_only_trackers_covering_it(live_server, page, ...):
    # three trackers: EMEA, EMEA+APAC, none; choose Region "APAC" → one card visible; "Not set" → the bare one;
    # Business line "Not set" plus chip "All" → the bare one.
```

- [ ] **Step 2: Run to verify they fail** — `WT=$PWD ../tools/acc-test.sh tests/test_home_labels.py tests/test_home_labels_browser.py -q`; Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify they pass** — same command plus `tests/test_trackers.py tests/test_report.py tests/test_report_page_browser.py -q`; Expected: PASS. Then the full suite in the background (`WT=$PWD ../tools/acc-test.sh -q`, about 13 minutes); Expected: all pass. Check the home page, the regions screen and a team page at 390 px and 1,440 px, light and dark, against the preview server (`scratchpad/tools/serve-preview.sh` with `WT` set).
- [ ] **Step 5: Commit** — `feat: home filters and report header show business line and regions`
