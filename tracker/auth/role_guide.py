"""What each tracker role can do: the rows of the table the app shows (``trackers/_role_guide.html``).

Each row names the routes it describes, and ``tests/test_role_guide.py`` checks that every one of them requires the
row's role, so the table cannot drift from what the app enforces.
"""

from __future__ import annotations

from typing import NamedTuple

from .roles import ROLE_ORDER


class RoleRow(NamedTuple):
    text: str  # "{location}" and "{locations}" become the tracker's own name for its groups, or "group(s)"
    role: str  # the lowest role that can do it
    endpoints: tuple[str, ...]


ROLE_GUIDE: tuple[RoleRow, ...] = (
    RoleRow(
        "Open the report and download it as PDF or PNG",
        "viewer",
        ("report.view", "report.export_pdf", "report.export_png", "report.chart_data", "report.chart_image"),
    ),
    RoleRow(
        "Record, edit and delete entries; download entries",
        "editor",
        (
            "entries.list_entries",
            "entries.new_entry",
            "entries.edit_entry",
            "entries.delete_entry",
            "entries.entries_csv",
        ),
    ),
    RoleRow(
        "Write the weekly update; set a calendar reminder",
        "editor",
        (
            "entries.inputs",
            "entries.calendar_reminder",
            "entries.calendar_reminder_history",
            "entries.calendar_reminder_history_panel",
            "entries.calendar_reminder_ics",
            "entries.calendar_reminder_resend",
        ),
    ),
    RoleRow(
        "Add, edit and delete risks; set weekly targets",
        "editor",
        ("entries.risks", "entries.new_risk", "entries.edit_risk", "entries.delete_risk", "entries.targets"),
    ),
    RoleRow(
        "Set a {location}'s status, planned date, ready figure and comment",
        "editor",
        ("trackers.groups", "trackers.set_group_status", "trackers.edit_group"),
    ),
    # The groups page and edit_group are editors' pages; their owner-only actions (add, retire, delete, reorder, and
    # the name, baseline and starting figure) are refused to editors inside them, which tests/test_role_guide.py checks.
    RoleRow(
        "Add, retire, delete and reorder {locations}; change a {location}'s name, baseline and starting figure",
        "owner",
        ("trackers.new_group",),
    ),
    RoleRow("Change the tracker's settings", "owner", ("trackers.settings",)),
    RoleRow(
        "Preview, test and send the report email",
        "owner",
        ("mail.settings", "mail.preview", "mail.test_send", "mail.send_now"),
    ),
)

# Tracker routes the table does not describe, and why. tests/test_role_guide.py requires every tracker route to be in
# a row or here, so a new route cannot be left out of the table unnoticed.
NOT_IN_GUIDE: dict[str, str] = {
    "trackers.view": "the tracker's own address, which opens its first page",
    "trackers.role_guide": "this table",
    "trackers.archive": "administrators only (the administrator note says so)",
}

ROLE_NOTES: tuple[str, ...] = (
    "Administrators can do everything on every tracker, including archiving it.",
    "An archived tracker cannot be changed by anyone.",
    "If you have a role from more than one place, the highest one counts.",
    "People with Manage teams choose who has which role.",
)

ROLES_SHOWN = ("viewer", "editor", "owner")


def role_guide_rows(location: str | None = None, locations: str | None = None) -> list[dict]:
    """The rows to show: the text with the tracker's own name for its groups (the generic "group" without one, as the
    tracker's tabs say), and for each role whether it can do the row's action."""
    one = (location or "group").lower()
    many = (locations or f"{one}s").lower()
    return [
        {
            "text": row.text.format(location=one, locations=many),
            **{role: ROLE_ORDER[role] >= ROLE_ORDER[row.role] for role in ROLES_SHOWN},
        }
        for row in ROLE_GUIDE
    ]
