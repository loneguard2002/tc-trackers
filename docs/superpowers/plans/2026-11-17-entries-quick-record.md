# Entries quick record and tidier list Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One quick-record form that keeps the location and date after Record, and an easier-to-read entries list.

**Architecture:** `list_entries` becomes a thin wrapper around `_render_list(tracker, form, errors, status)`. A POST to
`/entries/new` either renders that page with errors (400) or stores this tracker's last record in
`session["quick_add"]` and redirects to the list with its filters. The list pops that value to pre-fill the form,
show the result line and highlight the new row. CSS and template changes cover B.

**Tech Stack:** Flask, Jinja, SQLAlchemy, vanilla JS, Playwright browser tests.

**Spec:** `docs/superpowers/specs/2026-11-17-entries-quick-record-design.md`

## Global Constraints

- Works without JavaScript; strict CSP (no inline styles or scripts).
- Result line wording: `Recorded {quantity} for {location} on {dd Mon yyyy}.` (`format_date`).
- Chip label: `{unit_label or 'units'|capitalize} recorded by {group_label or 'group'|lower}`.
- British English, no contractions in copy.

## Review Focus

- A refused entry keeps every typed value, including the note, and shows each error once.
- The session value from tracker 1 must never pre-fill tracker 2's form.
- A retired location chosen last time must not stay pre-selected (it is not in the list).
- Filters with a bad week or group value in the POST must not break the redirect.
- Narrow screen: long notes wrap by word, not by letter.

---

### Task 1: Quick record (A)

**Files:** `tracker/entries/views.py`, `tracker/templates/entries/list.html`, delete `tracker/templates/entries/new.html`,
`tracker/templates/home.html`, `tracker/static/entries.js`, `tracker/static/tracker.css`; tests in
`tests/test_entries.py`, `tests/test_roles.py`, `tests/test_home.py`, browser test in `tests/test_registers_browser.py`.

- [ ] Tests: GET `/entries/new` → 302 to the list; Record → 302 to the list keeping `week`/`group` filters; next list
  view has the location selected, the date set, `autofocus` on Quantity, the result line and `is-new` on the row;
  a second view does not; another tracker's list is not pre-filled; refused entry → 400 on the list page with the
  error, values kept; quick-add date has `max` = today; Home links to the list.
- [ ] Implement, run `tests/test_entries.py tests/test_roles.py tests/test_home.py`, commit.

### Task 2: Tidier list (B)

- [ ] Tests: visible headings; chips show quantity sums and the label; browser test at 390 px: a long note is not
  broken mid-word and Edit/Delete share one line at 1280 px.
- [ ] Implement, run the entries tests and the browser test, commit.
