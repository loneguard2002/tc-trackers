"""The import template: a workbook in the layout ``workbook.py`` reads, with instructions and a worked example.

The stored file (``import-template.xlsx`` beside this module) is what the import page serves. ``flask
build-import-template`` rewrites it from ``build_template``, and a test compares the two so that a change to the
layout cannot leave the stored file behind. The example is the Network refresh tracker; ``example_leftovers`` names
the example values a workbook still holds, for a warning on the preview page.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .workbook import (
    GROUP_ROWS,
    RAG_VALUES,
    REPORT_DAYS,
    RISK_ROWS,
    RISK_STATUSES,
    SHEET_GROUPS,
    SHEET_INPUTS,
    SHEET_RISKS,
    SHEET_SETTINGS,
    SHEET_WEEKS,
    WEEK_ROWS,
    ImportPreview,
)

TEMPLATE_PATH = Path(__file__).with_name("import-template.xlsx")

INPUT = PatternFill("solid", fgColor="FFF4CC")  # cells the importer reads
HEAD = Font(bold=True)
TITLE = Font(bold=True, size=14)
DATE = "dd/mm/yyyy"

# --- The worked example -------------------------------------------------------------------------------------------

FIRST_REPORT = date(2026, 9, 18)
LAST_REPORT = date(2027, 6, 18)
WEEKS = 40
EXAMPLE_GROUPS = [
    # name, baseline, completed so far, ready but not complete, planned completion, RAG, comment
    ("London", 90, 18, 2, date(2027, 3, 26), "Green", "Floors 1 to 3 done"),
    ("New York", 60, 7, 1, date(2027, 5, 28), "Amber", "Change freeze in December"),
    ("Geneva", 30, 0, 0, date(2027, 6, 18), None, "Starts in January"),
]
EXAMPLE_TARGETS = [0, 2] + [3] * 6 + [5] * 32  # 180 over 40 weeks
EXAMPLE_ACTUALS = [0, 0, 2, 6, 4, 5, 3, 5]  # 25 done in the first eight weeks
EXAMPLE_RISKS = [
    # ref, description, impact, location, owner, raised, target, status, RAG, latest update
    ("R-03", "Out-of-hours building access not yet agreed", "Weekend work cannot start", "London", "Facilities",
     date(2026, 10, 2), date(2026, 11, 13), "Open", "Amber", "Request with the building manager"),
    ("R-05", "Spare switch stock below ten units", "Failed units cannot be swapped", None, "Procurement",
     date(2026, 10, 16), date(2026, 12, 4), "In progress", "Green", "Order placed"),
    ("R-07", "Firmware defect on the replacement switches may delay floor 4", "Floor 4 slips a week", "London",
     "Network lead", date(2026, 11, 3), date(2026, 11, 20), "Open", "Red", "Vendor fix due on 13 November"),
]  # fmt: skip
EXAMPLE_REPORT = date(2026, 11, 6)
EXAMPLE_UPDATE = (
    "London floor 3 cut over on Tuesday.\nTwo switches held back for a firmware fix.\nFloor 4 starts on Monday."
)
EXAMPLE_DECISIONS = "Approve the out-of-hours window on 21 November so floor 5 can be done over the weekend."

INSTRUCTIONS = [
    ("How to use this template", TITLE),
    ("This workbook creates a new tracker when you upload it on the Import workbook page.", None),
    ("It is filled in with an example, the Network refresh tracker. Replace the example with your own figures.", None),
    ("Only the shaded cells are read. Everything else is a label or a help column and may be left as it is.", None),
    ("", None),
    ("The sheets", HEAD),
    (f"{SHEET_SETTINGS}: the report day, the first and last report dates (at most 52 weeks apart), the target "
     "completion date, anything completed before the first report, and the weeks in the moving average.", None),
    (f"{SHEET_GROUPS}: up to {len(GROUP_ROWS)} locations (or other groups), one per row: name, total scope, completed "
     "so far, ready but not complete, planned completion, RAG and a comment. Keep the Total row below them.", None),
    (f"{SHEET_WEEKS}: one row per week from the first report: the weekly target and what was actually done. Leave "
     "future weeks' actuals blank.", None),
    (f"{SHEET_RISKS}: up to {len(RISK_ROWS)} risks or issues. Rows without a description are skipped.", None),
    (f"{SHEET_INPUTS}: the latest week's status, update and decisions needed. Each line of the update becomes a "
     "bullet point in the weekly email.", None),
    ("", None),
    ("The rules", HEAD),
    ("Dates must be real Excel dates (type 18/09/2026), not text.", None),
    ("Use the drop-down lists for RAG (Green, Amber, Red), risk status and the report day.", None),
    ("Figures are whole numbers. A simple sum such as =3+2 is accepted; other formulas are not.", None),
    (f"The 'completed so far' figures on {SHEET_GROUPS} must add up to the figure completed before the first report "
     f"plus all the actuals on {SHEET_WEEKS}. The import shows any difference before anything is saved.", None),
    ("", None),
    ("Importing", HEAD),
    ("Save the file as .xlsx (at most 1 MB), open Import workbook, choose the file and the week-ending day, and check "
     "the preview. The preview warns about any example values still in the workbook.", None),
    ("The tracker's name, unit and team are entered on the import screen, not in this workbook.", None),
]  # fmt: skip


def _list(sheet, values, cells: str) -> None:
    rule = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    rule.add(cells)
    sheet.add_data_validation(rule)


def _input(cell, value=None, number_format: str | None = None) -> None:
    cell.fill = INPUT
    if value is not None:
        cell.value = value
    if number_format:
        cell.number_format = number_format


def _header(sheet, title: str, note: str, headings: list[str]) -> None:
    sheet["A1"] = title
    sheet["A1"].font = TITLE
    sheet["A2"] = note
    for column, heading in enumerate(headings, start=1):
        sheet.cell(4, column, heading).font = HEAD


def _settings(sheet) -> None:
    sheet["A1"], sheet["A1"].font = "Settings", TITLE
    sheet["A2"] = "The reporting period. Only the shaded cells are read."
    rows = [
        (5, "Report day", "Friday", None),
        (6, "First report date", FIRST_REPORT, DATE),
        (7, "Last report date (at most 51 weeks after the first)", LAST_REPORT, DATE),
        (8, "Target completion date (optional)", LAST_REPORT, DATE),
        (9, "Completed before the first report", 0, None),
        (10, "Weeks in the moving average (1 to 12)", 3, None),
    ]
    for row, label, value, number_format in rows:
        sheet.cell(row, 1, label)
        _input(sheet.cell(row, 2), value, number_format)
    _list(sheet, REPORT_DAYS, "B5")
    sheet.column_dimensions["A"].width = 52
    sheet.column_dimensions["B"].width = 16


def _groups(sheet) -> None:
    _header(
        sheet,
        "By location",
        f"One location per row, rows 5 to {GROUP_ROWS[-1]}. Columns E and F are not read.",
        ["Location", "Total scope", "Completed so far", "Ready, not complete", "", "", "Planned completion", "RAG",
         "Comment"],
    )  # fmt: skip
    for index, row in enumerate(GROUP_ROWS):
        example = EXAMPLE_GROUPS[index] if index < len(EXAMPLE_GROUPS) else (None,) * 7
        name, baseline, completed, ready, planned, rag, comment = example
        for column, value in ((1, name), (2, baseline), (3, completed), (4, ready), (8, rag), (9, comment)):
            _input(sheet.cell(row, column), value)
        _input(sheet.cell(row, 7), planned, DATE)
    total = GROUP_ROWS[-1] + 1
    sheet.cell(total, 1, "Total").font = HEAD
    for column in "BCD":
        sheet[f"{column}{total}"] = f"=SUM({column}{GROUP_ROWS[0]}:{column}{GROUP_ROWS[-1]})"
    _list(sheet, RAG_VALUES, f"H{GROUP_ROWS[0]}:H{GROUP_ROWS[-1]}")
    for column, width in (("A", 22), ("B", 12), ("C", 16), ("D", 18), ("G", 18), ("H", 10), ("I", 30)):
        sheet.column_dimensions[column].width = width


def _weeks(sheet) -> None:
    _header(
        sheet,
        "Weekly tracker",
        "One row per week from the first report date. Column A follows the Settings sheet and is not read.",
        ["Report date", "Weekly target", "Actually done"],
    )
    for index, row in enumerate(WEEK_ROWS):
        date_cell = sheet.cell(row, 1, f"=Settings!$B$6+{7 * index}")
        date_cell.number_format = DATE
        target = EXAMPLE_TARGETS[index] if index < WEEKS else None
        actual = EXAMPLE_ACTUALS[index] if index < len(EXAMPLE_ACTUALS) else None
        _input(sheet.cell(row, 2), target)
        _input(sheet.cell(row, 3), actual)
    for column, width in (("A", 14), ("B", 14), ("C", 14)):
        sheet.column_dimensions[column].width = width


def _risks(sheet) -> None:
    _header(
        sheet,
        "Risks and issues",
        f"Up to {len(RISK_ROWS)} rows, {RISK_ROWS[0]} to {RISK_ROWS[-1]}. Rows without a description are skipped.",
        [
            "Ref",
            "Description",
            "Impact",
            "Location",
            "Owner",
            "Raised",
            "Target date",
            "Status",
            "RAG",
            "Latest update",
        ],
    )
    for index, row in enumerate(RISK_ROWS):
        example = EXAMPLE_RISKS[index] if index < len(EXAMPLE_RISKS) else (None,) * 10
        for column, value in enumerate(example, start=1):
            _input(sheet.cell(row, column), value, DATE if column in (6, 7) else None)
    _list(sheet, RISK_STATUSES, f"H{RISK_ROWS[0]}:H{RISK_ROWS[-1]}")
    _list(sheet, RAG_VALUES, f"I{RISK_ROWS[0]}:I{RISK_ROWS[-1]}")
    widths = (("A", 8), ("B", 44), ("C", 28), ("D", 12), ("E", 16), ("F", 12), ("G", 12), ("H", 12), ("I", 8),
              ("J", 34))  # fmt: skip
    for column, width in widths:
        sheet.column_dimensions[column].width = width


def _inputs(sheet) -> None:
    sheet["A1"], sheet["A1"].font = "Report inputs", TITLE
    sheet["A2"] = "The latest week's report. Optional: leave B7 to B9 blank to import none."
    rows = [
        (5, "Report date", EXAMPLE_REPORT, DATE),
        (7, "Status (RAG)", "Green", None),
        (8, "This week (one point per line)", EXAMPLE_UPDATE, None),
        (9, "Needed from you (one point per line)", EXAMPLE_DECISIONS, None),
    ]
    for row, label, value, number_format in rows:
        sheet.cell(row, 1, label)
        _input(sheet.cell(row, 2), value, number_format)
        sheet.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    _list(sheet, RAG_VALUES, "B7")
    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 70


def build_template() -> Workbook:
    workbook = Workbook()
    guide = workbook.active
    guide.title = "Instructions"
    for row, (text, font) in enumerate(INSTRUCTIONS, start=1):
        cell = guide.cell(row, 1, text or None)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if font is not None:
            cell.font = font
    guide.column_dimensions["A"].width = 110
    _settings(workbook.create_sheet(SHEET_SETTINGS))
    _groups(workbook.create_sheet(SHEET_GROUPS))
    _weeks(workbook.create_sheet(SHEET_WEEKS))
    _risks(workbook.create_sheet(SHEET_RISKS))
    _inputs(workbook.create_sheet(SHEET_INPUTS))
    return workbook


def write_template(path: Path | str = TEMPLATE_PATH) -> None:
    build_template().save(path)


def example_leftovers(preview: ImportPreview) -> list[str]:
    """The example values ``preview`` still holds, each named for the preview's warning."""
    found = []
    names = {group[0] for group in EXAMPLE_GROUPS}
    found += [f"Location “{g['name']}”" for g in preview.groups if g["name"] in names]
    descriptions = {risk[1]: risk[0] for risk in EXAMPLE_RISKS}
    found += [f"Risk {r['ref']} “{r['description']}”" for r in preview.risks if r["description"] in descriptions]
    if preview.inputs and " ".join((preview.inputs.get("headline") or "").split()) == " ".join(EXAMPLE_UPDATE.split()):
        found.append("The weekly update")
    return found
