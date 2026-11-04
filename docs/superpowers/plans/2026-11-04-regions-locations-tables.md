# Regions and Locations tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single "Regions and locations" screen with capacity-style **Regions** and **Locations** tables
(search, status buttons with counts, sortable columns, pop-up Add and Edit), and give each location a code and an ISO-2
country with a locally stored flag.

**Architecture:** A new `tracker/lists/countries.py` holds the fixed ISO-2 list; flag SVGs sit under
`tracker/static/flags/`. Migration 0005 adds `locations.code` and `locations.country_code`, converts and drops the typed
`country`. `tracker/lists/views.py` serves two table pages; each page holds one Add and one Edit `<dialog>`. Without
JavaScript the Add and Edit links go to `/new` and `/<id>/edit`, which render the same table page with that dialog
`open` and filled by the server; a new `static/lists.js` opens the dialogs modally and runs search, filters and sorting.

**Tech Stack:** Flask 3.1, SQLAlchemy 2, Jinja, Postgres, Alembic, pytest, Playwright, flag-icons 7.5.0 (MIT).

**Spec:** `docs/superpowers/specs/2026-11-03-regions-locations-tables-design.md` (builds on
`docs/superpowers/specs/2026-11-02-regions-locations-business-lines-design.md`, stage 1, merged).

## Global Constraints

- Strict CSP: no inline script, inline style or `on…=` attributes; images from tc-trackers only (`img-src 'self' data:`).
  No request to any outside site at run time.
- CSRF on every POST (`csrf_field(csrf_token())`); works without JavaScript; light and dark themes; no page-level
  horizontal scroll at 390 px (the table scrolls inside its own frame); Alembic migration for every schema change.
- British formal copy in the active voice, no contractions.
- Administrators only: every list route uses `manage_lists_required` (already defined in `tracker/lists/views.py`).
- Every change commits with its Activity entry in one transaction; existing Activity action names stay unchanged.
- Entries in use are retired, never deleted; Delete is offered only when nothing uses the entry, and the server refuses
  it again (`REGION_IN_USE`, `LOCATION_IN_USE` unchanged).
- Location code: required on every save, 2 to 6 letters A–Z, stored upper-case after trimming, unique ignoring case.
- Country: one of the 249 ISO 3166-1 alpha-2 codes, stored upper-case in `locations.country_code`; the name and flag
  always come from the code. City plus country code are unique, city ignoring case.
- No tick boxes and no bulk actions. Business lines page unchanged.
- Commit identity: `git -c user.name="Alex Krovina" -c user.email="alex.krovina@tradition.ch" commit`, message ending
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tests: `WT=$PWD ../tools/acc-test.sh <pytest args>` from the worktree, sandbox disabled (database
  `tracker_test_design`); `/mnt/c/Users/AlexKrovina/Documents/GitHub/tc-trackers/.venv/bin/ruff check` and
  `ruff format --check` clean.

## Plan rulings (made while writing the plan; the spec is silent or cannot be met literally)

- Country names come from flag-icons' `country.json` (common English names: "United Kingdom", "South Korea"), with
  one override, `US` → "United States", to match how capacity and Tradition write it. The spec said "English short
  names from ISO 3166-1"; the official forms ("United Kingdom of Great Britain and Northern Ireland (the)") are too long
  for a table cell. Cost if wrong: one data file.
- A `<select>` option cannot hold an image, so options read "United Kingdom (GB)" and the flag of the chosen country
  shows beside the list. Cost if wrong: none; emoji flags do not draw on Windows.
- Status wording: filter buttons **All / Active / Retired**, row badge **Active** or **Retired**, to match the Retire
  action used across tc-trackers (capacity says "Inactive"). Cost if wrong: copy only.
- The migration imports `match_country` from `tracker/lists/countries.py`. It runs once on data typed in the two days
  since stage 1, so later edits to the list cannot matter.

## Review Focus

1. A location created before this change (no code, no country) is opened in Edit: the dialog opens with both fields
   empty, Save refuses with both messages beside the fields, and Retire, Restore and Delete still work without a code.
   — Task 2 and Task 4 tests.
2. A code typed as " lon " is stored "LON"; then "Lon" for another location is refused as taken; "L0N", "L" and
   "LONDONX" are refused with the format message. — Task 2 tests.
3. A validation error on **Edit** reopens the Edit dialog for that same row with what was typed, not the Add dialog, and
   on Add reopens Add; with JavaScript the reopened dialog is modal. — Task 3, 4 and 5 tests.
4. A location in a retired region: Edit offers that region (marked retired) and saving it unchanged succeeds; the Add
   dialog does not offer retired regions. — Task 4 test.
5. Search text with brackets, dots or accents ("(", "São", "St.") filters as plain text with no script error, and the
   counts and footer follow the visible rows. — Task 5 browser test.

---

### Task 1: Country list and flags

**Files:**
- Create: `tracker/lists/countries.py`
- Create: `tracker/static/flags/<code>.svg` (249 files, lower-case ISO-2 names, from flag-icons 7.5.0 `flags/4x3/`)
- Create: `tracker/static/flags/LICENSE-flag-icons.txt` (the package's LICENSE, unchanged)
- Test: `tests/test_countries.py`

**Interfaces:**
- Produces:
  - `COUNTRIES: dict[str, str]` — upper-case code → name, ordered by name (case-insensitive), exactly 249 entries.
  - `country_name(code: str | None) -> str | None` — the name, or `None` for empty/unknown.
  - `match_country(text: str | None) -> str | None` — a code for a typed name or code, ignoring case and surrounding
    spaces; also the aliases `UK`→GB, `Great Britain`→GB, `England`→GB, `USA`→US, `United States of America`→US,
    `UAE`→AE, `Holland`→NL. Used only by the migration.
  - `parse_country(text: str | None) -> tuple[str | None, str | None]` — `(code, None)` for a listed code (ignoring
    case and spaces), `(None, COUNTRY_REQUIRED)` for empty, `(None, COUNTRY_CHOICE_ERROR)` otherwise.
  - `COUNTRY_REQUIRED = "Choose a country."`, `COUNTRY_CHOICE_ERROR = "Choose a country from the list."`
  - `flag_path(code: str) -> str` — `"flags/" + code.lower() + ".svg"` (for `url_for('static', filename=...)`).

- [ ] **Step 1: Fetch the flags.** Download `https://registry.npmjs.org/flag-icons/-/flag-icons-7.5.0.tgz` into
  `$TMPDIR` (its own empty directory), extract, and copy `flags/4x3/<code>.svg` for each entry of `country.json` with
  `"iso": true` (249) to `tracker/static/flags/`, and `LICENSE` to `tracker/static/flags/LICENSE-flag-icons.txt`. Generate
  `COUNTRIES` from the same `country.json` (names as given, except `US`, which becomes "United States"); the
  generating script is not committed. Head the module with a docstring naming the source and
  version.

- [ ] **Step 2: Write the failing tests** in `tests/test_countries.py`:

```python
def test_list_has_every_iso_code_once_sorted_by_name():
    assert len(COUNTRIES) == 249
    assert all(len(c) == 2 and c.isupper() for c in COUNTRIES)
    names = list(COUNTRIES.values())
    assert names == sorted(names, key=str.casefold)

def test_names():
    assert country_name("GB") == "United Kingdom"
    assert country_name("us") == "United States"
    assert country_name("CH") == "Switzerland"
    assert country_name("XX") is None and country_name(None) is None and country_name("") is None

def test_match_country_names_codes_and_aliases():
    for text, code in [("United Kingdom", "GB"), (" uk ", "GB"), ("USA", "US"),
                       ("United States of America", "US"), ("united arab emirates", "AE"), ("UAE", "AE"),
                       ("ch", "CH"), ("Switzerland", "CH")]:
        assert match_country(text) == code
    assert match_country("Atlantis") is None and match_country("") is None and match_country(None) is None

def test_parse_country():
    assert parse_country(" gb ") == ("GB", None)
    assert parse_country("") == (None, COUNTRY_REQUIRED)
    assert parse_country("ZZ") == (None, COUNTRY_CHOICE_ERROR)
    assert parse_country("United Kingdom") == (None, COUNTRY_CHOICE_ERROR)

def test_every_country_has_a_flag_file():
    root = Path(__file__).parent.parent / "tracker" / "static"
    assert all((root / flag_path(code)).is_file() for code in COUNTRIES)
    assert (root / "flags" / "LICENSE-flag-icons.txt").is_file()
```

- [ ] **Step 3: Run** `WT=$PWD ../tools/acc-test.sh tests/test_countries.py -q` — Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `tracker/lists/countries.py` (no Flask or database imports).
- [ ] **Step 5: Run** the same command — Expected: 5 passed.
- [ ] **Step 6: Commit** `feat: ISO country list and local flag images`.

### Task 2: Location code and country code (schema, rules, labels)

**Files:**
- Create: `migrations/versions/0005_location_code_country_code.py`
- Modify: `tracker/models.py` (`Location`), `tracker/lists/catalogue.py`, `tracker/teams/views.py`,
  `tracker/lists/views.py` (location form and checks only), `tracker/templates/lists/regions.html` (the location
  fields only, so the old page keeps working until Task 4 replaces it), `tests/conftest.py` (`location_factory`)
- Test: `tests/test_migration_0005.py`, `tests/test_migration_matches_models.py`, `tests/test_lists_admin.py`,
  `tests/test_lists_catalogue.py`, `tests/test_team_places.py` and the other tests that build locations

**Interfaces:**
- Consumes: Task 1 `country_name`, `match_country`, `parse_country`, `COUNTRY_*`.
- Produces:
  - `Location.code: Mapped[str | None]` (Text), `Location.country_code: Mapped[str | None]` (Text); `Location.country`
    removed. Indexes: `uq_locations_code_lower` on `lower(code)` unique; `uq_locations_city_country_code` on
    `(lower(city), country_code)` unique (replaces `uq_locations_city_country_lower`).
  - `location_label(city: str, country_code: str | None) -> str` — "Geneva, Switzerland", or "Geneva" when the country
    is unset. Every caller passes `location.country_code`.
  - In `tracker/lists/views.py`: `LOCATION_CODE_REQUIRED = "Enter a location code."`,
    `LOCATION_CODE_FORMAT = "A location code is 2 to 6 letters, such as LON."`,
    `LOCATION_CODE_TAKEN = "A location with that code already exists."`;
    `_location_form() -> dict` returns `{"code": <stripped, upper-cased>, "city": ..., "country_code": <raw stripped>}`;
    `_location_errors(code, city, country_text, exclude_id=None) -> tuple[list[str], str | None]` returns the errors and
    the parsed country code. POST fields are `code`, `city`, `country_code` (and `region_id` on update).
  - `location_factory(region, city="Geneva", country_code="CH", code=None, retired=False)`; when `code` is `None` the
    factory uses the first three letters of the city, upper-cased, so existing callers keep unique codes where cities
    differ.
  - Activity details: `location_created` → `{"location": label, "code": code, "region": region.code}`;
    `location_changed` before/after keys `code`, `city`, `country` (country **names**, `None` shown as empty), `region`.

- [ ] **Step 1: Write the failing migration tests** in `tests/test_migration_0005.py`, using a fixture
  `at_revision_0004` modelled on `tests/test_migration_0004.py`, inserting rows with raw SQL:

```python
def test_upgrade_converts_typed_countries(db, at_revision_0004):
    region = _region(db, "EMEA")
    rows = {city: _location(db, region, city, country) for city, country in
            [("London", "United Kingdom"), ("Leeds", "uk"), ("Dubai", "UAE"), ("Atlantis", "Atlantis")]}
    db.commit()
    command.upgrade(alembic_config(), "head")
    got = {city: db.get(Location, i).country_code for city, i in rows.items()}
    assert got == {"London": "GB", "Leeds": "GB", "Dubai": "AE", "Atlantis": None}
    assert all(db.get(Location, i).code is None for i in rows.values())

def test_upgrade_refuses_two_rows_that_become_the_same_place(db, at_revision_0004):
    region = _region(db, "EMEA")
    _location(db, region, "London", "United Kingdom"); _location(db, region, "london", "UK")
    db.commit()
    with pytest.raises(RuntimeError, match="London"):
        command.upgrade(alembic_config(), "head")

def test_downgrade_restores_country_names(db): ...  # head → 0004: country holds country_name(code), "" when unset
```

  Add `Location.code` and `Location.country_code` to whatever `tests/test_migration_matches_models.py` compares.

- [ ] **Step 2: Write the failing rule tests** in `tests/test_lists_admin.py` (adapt every existing location test to
  the new fields first; none may be weakened):

```python
def test_location_code_is_trimmed_and_upper_cased(...):    # code " lon " → stored "LON", country_code "gb" → "GB"
def test_location_code_format(...):                         # "L", "LONDONX", "L0N", "LO N" → LOCATION_CODE_FORMAT, 400
def test_location_code_taken_ignoring_case(...):            # second location code "Lon" → LOCATION_CODE_TAKEN, 400
def test_location_country_required_and_listed(...):         # "" → COUNTRY_REQUIRED; "ZZ" → COUNTRY_CHOICE_ERROR
def test_same_city_and_country_refused(...):                # ("geneva","CH") after ("Geneva","CH") → LOCATION_TAKEN
def test_same_city_other_country_allowed(...):              # ("London","CA") after ("London","GB") → 302
def test_old_location_without_code_must_get_one_on_save(...):  # row with code/country NULL: save without → both
                                                               # LOCATION_CODE_REQUIRED and COUNTRY_REQUIRED
def test_old_location_without_code_can_retire_restore_delete(...):
def test_location_activity_names_code_and_country(...):     # created detail has "code"; changed shows country names
```

  In `tests/test_lists_catalogue.py` / `tests/test_team_places.py`: `location_label("Geneva", "CH") ==
  "Geneva, Switzerland"`, `location_label("Geneva", None) == "Geneva"`, and the team label reads
  "Geneva, Switzerland (EMEA)".

- [ ] **Step 3: Run** `WT=$PWD ../tools/acc-test.sh tests/test_migration_0005.py tests/test_lists_admin.py
  tests/test_lists_catalogue.py tests/test_team_places.py -q` — Expected: FAIL.
- [ ] **Step 4: Implement** the model, migration 0005 (`down_revision = "0004"`; add both columns nullable, convert
  each row with `match_country`, check for `(lower(city), country_code)` collisions among converted rows and raise
  `RuntimeError` naming the cities and countries before any change is committed, drop the old index and `country`,
  create both new indexes; downgrade re-adds `country` NOT NULL filled from `country_name` or `""`), the catalogue and
  teams label changes, the factory, and the location rules in `views.py`. Code check: `re.fullmatch(r"[A-Z]{2,6}",
  code)` after upper-casing. On the old `regions.html`, swap the country text inputs for `code` and `country_code`
  text inputs (Task 4 replaces the page).
- [ ] **Step 5: Run** the full suite `WT=$PWD ../tools/acc-test.sh -q -x` — Expected: all pass (skips as before).
- [ ] **Step 6: Commit** `feat: locations have a code and an ISO country`.

### Task 3: Regions table page with Add and Edit dialogs

**Files:**
- Modify: `tracker/lists/views.py` (region routes and rendering), `tracker/templates/base.html` (nav),
  `tracker/static/tracker.css` (list-table, code badge, dialog styles, shared with Task 4)
- Create: `tracker/templates/lists/_table.html` (macros shared with Task 4), `tracker/templates/lists/regions.html`
  (rewritten as the Regions table; the location parts move to Task 4's page)
- Test: `tests/test_lists_admin.py`

**Interfaces:**
- Produces routes (all `manage_lists_required`): `GET /admin/regions` (`lists.regions`), `GET /admin/regions/new`
  (`lists.new_region`), `GET /admin/regions/<id>/edit` (`lists.edit_region`); `POST /admin/regions` and
  `POST /admin/regions/<id>` unchanged in fields and actions. Success redirects to `lists.regions` with anchor
  `region-<id>`.
- `_render_regions(errors, status, form=None, dialog=None, edit_id=None)` where `dialog` is `None`, `"add"` or `"edit"`;
  the template renders that dialog with the `open` attribute and `data-reopen`, the errors inside it beside the
  fields, and the typed values.
- Macros in `lists/_table.html` (Task 4 reuses them): `code_badge(code, fallback)` (fallback shown muted when `code`
  is empty), `status_badge(retired)`, `status_filters(target_id, noun)` (rendered `hidden`; buttons
  `data-status="all|active|retired"` with `[data-count]` spans), `search_box(target_id, label)` (rendered `hidden`),
  `table_foot(noun_plural)` (with `[data-shown]`, `[data-total]`, `[data-active]`), `sort_header(label, key)`
  (`<th aria-sort="none"><button type="button" data-sort="key" hidden>` plus the label as plain text visible without
  JavaScript), `row_actions(edit_url, state_url, retired, what, in_use)` (Edit link with `data-dialog-open="edit"`,
  Retire/Restore icon button with a visible-to-screen-readers label, Delete icon button only when not in use, using
  `data-confirm` as today).
- Rows: `<tr id="region-<id>" data-search="<code> <name> lower" data-status="active|retired"
  data-sort-code=… data-sort-name=… data-sort-locations=… data-sort-teams=… data-sort-status=…
  data-edit='{"code":…,"name":…,"action":"/admin/regions/<id>"}'>` (JSON via `|tojson`, read by Task 5).
- Copy: page title "Regions"; sub-title "Regions group locations, and trackers say which regions they cover.";
  Add button "Add region"; dialog titles "Add region" / "Edit region EMEA"; fields "Code" (help "A short name such as
  EMEA, at most 20 characters.") and "Name"; buttons "Create region" / "Save" and "Cancel" (a link back to
  `lists.regions`); empty table "No regions yet. Add the first one."
- Columns: Code, Name, Locations (count, links to `lists.locations` with `?region=<id>`), Teams (teams whose location is
  in the region; links to the Teams page), Status, actions. Default order: code.
- Nav: "Regions" (`globe`, `current_page="regions"`) and, added in Task 4, "Locations".

- [ ] **Step 1: Write the failing tests:**

```python
def test_regions_table_lists_counts_and_status(...):   # two regions, 2 locations + 1 team in EMEA: row cells show
                                                       # "EMEA", full name, "2", "1", "Active"; retired one "Retired"
def test_region_delete_only_when_unused(...):          # unused row has a delete form; used row has none
def test_new_region_page_opens_add_dialog(...):        # GET /admin/regions/new → 200, <dialog id="add-dialog" … open
def test_edit_region_page_opens_filled_edit_dialog(...):  # GET /admin/regions/<id>/edit → edit dialog open, values
def test_edit_unknown_region_is_404(...):
def test_add_error_reopens_add_dialog_with_typed_values(...):   # duplicate code → 400, add dialog open, typed name
def test_edit_error_reopens_edit_dialog_for_that_region(...):   # 400, edit dialog open, action is that region's URL
def test_regions_pages_need_administrator(...):        # extend the existing access test with /new and /<id>/edit
def test_regions_page_has_no_inline_script_or_style(...):  # no "<script>" without src, no " style=", no " on…=" attrs
```

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_lists_admin.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the routes, `_render_regions`, the macros, the template and the CSS. The dialogs use the
  native `<dialog>` element; the server renders `open` only for the dialog named by `dialog`. Without JavaScript the
  Add button and Edit links are plain links to `/new` and `/<id>/edit`.
- [ ] **Step 4: Run** the full suite — Expected: all pass.
- [ ] **Step 5: Commit** `feat: regions table with add and edit dialogs`.

### Task 4: Locations table page

**Files:**
- Create: `tracker/templates/lists/locations.html`
- Modify: `tracker/lists/views.py`, `tracker/templates/base.html` (nav "Locations", a new `pin` icon: a map-pin path added
  to the `icon` macro in `tracker/templates/macros.html`), `tracker/static/tracker.css`
- Test: `tests/test_lists_admin.py`

**Interfaces:**
- Consumes: Task 1 `COUNTRIES`, `country_name`, `flag_path`; Task 2 location rules; Task 3 macros and dialog pattern.
- Produces routes: `GET /admin/locations` (`lists.locations`), `GET /admin/locations/new` (`lists.new_location`),
  `GET /admin/locations/<id>/edit` (`lists.edit_location`), `POST /admin/locations` (`lists.create_location`, fields
  `region_id`, `code`, `city`, `country_code`; replaces `POST /admin/regions/<id>/locations`, which is removed),
  `POST /admin/locations/<id>` unchanged in actions. Success redirects to `lists.locations` with anchor
  `location-<id>`. Region checks on create use `_parse_region(text, current_id=None)` (active regions only) with
  `REGION_CHOICE_ERROR`.
- Columns: Code (badge; muted first three letters of the city when unset), Name (city), Region ("EMEA — Europe,
  Middle East and Africa"), Country (flag `<img src="{{ url_for('static', filename=flag_path(code)) }}" alt="" width="20"
  height="15">` then the name, or muted "Country not set"), Teams (count, links to the Teams page), Status, actions.
  Default order: region code, then city.
- A region filter `<select data-region-filter hidden>` ("All regions", then each region "EMEA — Europe, …") beside the
  search box.
- Rows: `id="location-<id>"`, `data-search` (code, city, region code and name, country name, lower-case),
  `data-status`, `data-region="<region id>"`, `data-sort-*`, `data-edit` JSON with `code`, `city`, `country_code`,
  `region_id`, `teams`, `action`.
- Dialog fields, in order: Region (select; Add offers active regions; Edit adds the location's own retired region
  marked "(retired)"); Code and Name side by side (Code help "2 to 6 letters, such as LON."); Country (select, first
  option "Choose a country", then `COUNTRIES` as "United Kingdom (GB)"), with `<img data-flag-preview hidden alt="">`
  beside it (server renders it visible with the chosen flag when a country is set); on Edit, the team note
  "Used by 1 team. Changing the region moves the team with it." / "Used by N teams. Changing the region moves them to
  it." (kept from stage 1). Buttons "Create location" / "Save", "Cancel".
- Copy: page title "Locations"; sub-title "Teams are placed at a location, and each location belongs to one region.";
  Add button "Add location"; empty table "No locations yet." plus, when there are no active regions, "Add a region
  first." linking to `lists.regions`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_locations_table_shows_code_region_country_flag_teams(...):  # "LON", "London", "EMEA — Europe…",
                                                       # img src ends "/flags/gb.svg", "United Kingdom", team count
def test_location_without_code_or_country_shows_fallbacks(...):  # badge "LON" muted (class), "Country not set"
def test_create_location_posts_to_locations(...):     # POST /admin/locations → 302 to /admin/locations#location-<id>
def test_old_create_route_is_gone(...):               # POST /admin/regions/<id>/locations → 404 or 405
def test_create_location_refuses_retired_or_unknown_region(...):  # REGION_CHOICE_ERROR, 400, add dialog open
def test_country_options_cover_the_list(...):          # 249 options plus the prompt, "United Kingdom (GB)" present
def test_edit_location_in_retired_region_offers_it_and_saves_unchanged(...):  # option marked "(retired)"; save → no change
def test_edit_location_error_reopens_its_dialog(...):  # bad code on edit → 400, edit dialog open with typed code
def test_edit_location_shows_team_move_note(...):      # GET /admin/locations/<id>/edit with 2 teams → note text
def test_locations_pages_need_administrator(...):
def test_locations_page_has_no_inline_script_or_style(...):
```

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_lists_admin.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the routes, rendering and template; remove the location parts and route from the regions
  page and views.
- [ ] **Step 4: Run** the full suite — Expected: all pass.
- [ ] **Step 5: Commit** `feat: locations table with code, country and flag`.

### Task 5: Table and dialog behaviour (lists.js) and browser tests

**Files:**
- Create: `tracker/static/lists.js` (plain ES5 style like `admin.js`, loaded with `defer` on both pages)
- Modify: `tracker/templates/lists/regions.html`, `tracker/templates/lists/locations.html` (script tag)
- Test: `tests/test_lists_browser.py` (`@pytest.mark.browser`, modelled on `tests/test_teams_browser.py`)

**Interfaces:**
- Consumes: the data attributes and macros from Tasks 3 and 4.
- Behaviour:
  - Reveals the `hidden` search box, status buttons, region filter and sort buttons.
  - Search: case-insensitive plain substring of `data-search` (`indexOf`, never a regular expression), live on input.
  - Status buttons (`aria-pressed`), region filter and search combine; each status button's count is the number of
    rows matching the search and region filter with that status; the footer reads "Showing N of M locations" (or
    regions) and "K active", where M counts all rows.
  - Sort: clicking a header's button sorts the rows by its `data-sort-<key>` (numbers numerically, text with
    `localeCompare`), toggling ascending and descending, and sets `aria-sort` on that header and `none` on the others.
  - `?region=<id>` in the address presets the region filter on Locations.
  - `a[data-dialog-open="add"]` and `[data-dialog-open="edit"]` open the dialog with `showModal()` instead of
    following the link; Edit fills the dialog's fields, title, form `action` and team note from the row's `data-edit`
    and clears previous errors; Add clears the form. Cancel and Escape close it.
  - A dialog rendered with `data-reopen` is closed and reopened with `showModal()` on load.
  - Changing the Country select sets the flag preview's `src` to `/static/flags/<code lower>.svg` and shows it, or hides
    it for the prompt.

- [ ] **Step 1: Write the failing browser tests:**

```python
def test_search_filters_rows_and_counts(page, ...):    # 3 locations; type "lon" → 1 row visible, footer
                                                        # "Showing 1 of 3 locations", Active count 1
def test_search_with_special_characters_is_plain_text(page, ...):  # "(", "São", "St." → no page error, counts follow
def test_status_and_region_filters_combine(page, ...):  # Retired + APAC → only retired APAC rows
def test_sorting_toggles_and_sets_aria_sort(page, ...):  # click Name twice → descending, aria-sort="descending"
def test_add_dialog_is_modal_and_creates(page, ...):   # click Add location → dialog open modal, fill, submit → row
def test_edit_dialog_fills_from_row(page, ...):        # click Edit on LON → code "LON", country GB, flag src gb.svg
def test_edit_error_reopens_modal_edit_dialog(page, ...):  # submit bad code → page reloads with edit dialog modal
def test_country_change_updates_flag(page, ...):       # choose "Switzerland (CH)" → preview src ends "/flags/ch.svg"
def test_region_query_presets_filter(page, ...):       # /admin/locations?region=<apac id> → only APAC rows
def test_no_horizontal_scroll_at_390(page, ...):       # both pages: document.scrollingElement.scrollWidth <= 390
```

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_lists_browser.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `lists.js`.
- [ ] **Step 4: Run** the full suite — Expected: all pass.
- [ ] **Step 5: Commit** `feat: search, filters, sorting and dialogs on the regions and locations tables`.
