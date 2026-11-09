# Import Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A downloadable, example-filled import template with instructions, a guide on the import page, and a preview
warning for example values left in.

**Architecture:** `tracker/importer/template.py` builds the workbook from the importer's sheet and row constants and
holds the example values; the stored file `tracker/importer/import-template.xlsx` is written by
`flask build-import-template` and served by `GET /import/template`; the confirm page lists `example_leftovers`.

**Tech Stack:** Flask 3.1, openpyxl, pytest.

**Spec:** docs/superpowers/specs/2026-11-09-import-template-design.md

## Global Constraints

- Example: Network refresh, report day Friday, first report 18/09/2026, last 18/06/2027, target 18/06/2027, three
  locations (London 90/18, New York 60/7, Geneva 30/0), 40 weeks of targets, eight weeks of actuals totalling 25,
  three risks (R-03 Amber, R-05 Green, R-07 Red raised 03/11/2026), update for 06/11/2026.
- The stored template must import with no mismatch.
- Download and guide need the `import_workbooks` permission, like the import page.

## Review Focus

- The stored file and a freshly built one differ in any cell value, list or sheet → a test fails.
- A workbook with no example values shows no warning; one with a single example risk names only that risk.

---

### Task 1: Build the template, store it, serve it, warn about the example

**Files:** `tracker/importer/template.py`, `tracker/importer/import-template.xlsx`, `tracker/importer/views.py`,
`tracker/app.py` (command), `tracker/templates/importer/upload.html`, `tracker/templates/importer/confirm.html`,
`tests/importer/test_template.py`.

- `build_template() -> Workbook`; `TEMPLATE_PATH`; `write_template(path=TEMPLATE_PATH) -> None`;
  `example_leftovers(preview: ImportPreview) -> list[str]`.
- Tests: the stored template imports (no mismatch, 3 groups, 3 risks, inputs present); stored equals built (sheet
  names, every cell value, data validations); the download needs the permission and returns the file; the upload
  page links it and shows the guide; leftovers named for the template and absent for the fixture workbook; the
  command writes a file that equals the built one.
