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
        ("report.view", "report.export_pdf", "report.export_png"),
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
        "Write the weekly update; set a calendar reminder", "editor", ("entries.inputs", "entries.calendar_reminder")
    ),
    RoleRow(
        "Add and edit risks; set weekly targets",
        "editor",
        ("entries.risks", "entries.new_risk", "entries.edit_risk", "entries.targets"),
    ),
    RoleRow(
        "Set a {location}'s status, planned date, ready figure and comment",
        "editor",
        ("trackers.set_group_status", "trackers.edit_group"),
    ),
    RoleRow(
        "Add {locations}; change a {location}'s name, baseline and starting figure", "owner", ("trackers.new_group",)
    ),
    RoleRow("Change the tracker's settings; archive it", "owner", ("trackers.settings", "trackers.archive")),
    RoleRow(
        "Preview, test and send the report email",
        "owner",
        ("mail.settings", "mail.preview", "mail.test_send", "mail.send_now"),
    ),
)

ROLE_NOTES: tuple[str, ...] = (
    "Administrators can do everything on every tracker.",
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
