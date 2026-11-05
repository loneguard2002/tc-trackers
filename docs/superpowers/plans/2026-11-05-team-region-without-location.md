# Team Region Without Location Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A team can be placed in a region, such as Global, without a location.

**Architecture:** `teams` gains `region_id` (migration 0008). A composite foreign key `(location_id, region_id)` to
`locations (id, region_id)` with ON UPDATE CASCADE keeps a team's region equal to its location's region, including
when a location moves region. Readers use `Team.region_id`; the location stays optional.

**Tech Stack:** Flask 3.1, SQLAlchemy 2 (no `relationship()`), Jinja, Postgres, hand-written Alembic migrations,
pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-team-region-without-location-design.md`

**Branch:** `feat/team-region` from `feat/region-access` (cce88ef; its migration 0007 must merge first). **Tests:** from
the worktree, `WT=$PWD ../tools/acc-test.sh <args>` (sandbox disabled).

## Global Constraints

- Location first entry: "No specific location". Location help: "The city and country the team works in, if it works
  from one."
- Activity place text: "EMEA" alone without a location; "Geneva, Switzerland (EMEA)" with one.
- Tree and team page: "Global" alone without a location; "EMEA · Geneva" (tree) and "EMEA · Geneva, Switzerland"
  (team page) as today with one; "Region not set" when neither.
- A team's region grants nothing. Retired regions and locations cannot be chosen anew.
- Strict CSP, CSRF, works without JavaScript, light and dark, no horizontal scroll at 390 px, British formal copy in the
  active voice.

## Review Focus

1. **A location moving to another region:** its teams' region follows at once (pinned in Task 1,
   `test_moving_a_location_moves_its_teams_region`).
2. **A region chosen with a location from another region:** refused with `LOCATION_REGION_MISMATCH` (existing test
   kept).
3. **Deleting a region that only location-less teams use:** refused as in use (Task 2,
   `test_region_used_by_a_team_cannot_be_deleted`).
4. **A team saved with the region only, while that region is retired at the same moment:** a message, not an error
   page (the existing IntegrityError fallbacks re-run the parse).
5. **Existing teams after the upgrade:** each with a location has that location's region; teams with neither stay
   unset (Task 1, `test_upgrade_gives_teams_their_location_region`).

---

### Task 1: Store the team's region

**Files:**
- Modify: `tracker/models.py` (`Team.region_id`; `UniqueConstraint("id", "region_id")` on `Location` named
  `uq_locations_id_region_id`; the composite foreign key; a check)
- Create: `migrations/versions/0008_team_region.py`
- Test: `tests/test_migration_0008.py` (new), `tests/test_team_places.py`

**Interfaces:**
- Produces:
  - `Team.region_id: Mapped[int | None]`, foreign key to `regions.id` ON DELETE RESTRICT, index `ix_teams_region_id`.
  - `ForeignKeyConstraint(["location_id", "region_id"], ["locations.id", "locations.region_id"],
    name="fk_teams_location_id_region_id_locations", onupdate="CASCADE", ondelete="RESTRICT")`.
  - `CheckConstraint("location_id IS NULL OR region_id IS NOT NULL", name="location_has_region")`.
  - The migration fills `teams.region_id` from each team's location before adding the composite key; downgrade drops
    them and sets nothing else (teams without a location lose their region).

- [ ] **Step 1: Failing tests**
  - `test_upgrade_gives_teams_their_location_region`: downgrade to 0007, insert a team with a location and one with
    neither, upgrade; the first has its location's region, the second `None`. The test leaves the database at head.
  - `test_moving_a_location_moves_its_teams_region`: change `location.region_id` and commit; the team's `region_id`
    follows.
  - `test_a_team_location_must_be_in_its_region`: a team with a location and a different region fails to commit.
- [ ] **Step 2: Run, watch them fail.**
- [ ] **Step 3: Implement the model and migration 0008.** Every place that sets `Team.location_id` also sets
  `Team.region_id` (Task 2 does the forms; update fixtures in `tests/conftest.py` that create teams with a location).
- [ ] **Step 4: Full suite and ruff.**
- [ ] **Step 5: Commit** `feat: a team stores its region`

### Task 2: Forms, labels and counts

**Files:**
- Modify: `tracker/lists/catalogue.py`, `tracker/teams/views.py`, `tracker/templates/teams/_place_fields.html`,
  `tracker/templates/teams/_tree.html`, `tracker/templates/teams/team.html`, `tracker/lists/views.py`
- Test: `tests/test_team_places.py`, `tests/test_lists_catalogue.py`, `tests/test_lists_admin.py`

**Interfaces:**
- Consumes: `Team.region_id` (Task 1).
- Produces:
  - `parse_place(session, region_text, location_text, current_region_id, current_location_id) -> tuple[Region | None,
    Location | None, str | None]` replaces `parse_location`. The region is required (`REGION_REQUIRED = "Choose a
    region."`); a blank location is allowed; otherwise the existing choice and mismatch errors.
  - `Place` fields: `region_id: int`, `region_code: str`, `location_id: int | None`, `location: str | None`,
    `city: str | None`. `team_places` covers every team with a region.
  - `location_choices` returns every active region, with or without locations, plus a retired region kept by
    `keep_region_id`.

- [ ] **Step 1: Failing tests**
  - `test_a_team_can_have_a_region_without_a_location`: create with Global only; `region_id` set, `location_id` None;
    Activity `location` is "GLOBAL"; the tree shows "GLOBAL" alone and the team page "GLOBAL".
  - `test_region_without_locations_is_offered`: the New team Region select lists a region with no locations; the
    Location select starts with "No specific location".
  - `test_a_new_team_needs_a_region` (replaces `test_a_new_team_needs_a_region_and_a_location`): no region gives
    `REGION_REQUIRED`; a location without a region is refused.
  - `test_edit_can_clear_the_location`: Edit details with the region only clears the location and logs the change.
  - `test_region_used_by_a_team_cannot_be_deleted` and the Regions table Teams count includes a location-less team.
- [ ] **Step 2: Run, watch them fail.**
- [ ] **Step 3: Implement.** Keep the IntegrityError fallbacks re-running `parse_place`.
- [ ] **Step 4: Full suite and ruff; light and dark screenshots of New team at 1440 px and 390 px.**
- [ ] **Step 5: Commit** `feat: a team can be in a region without a location`
