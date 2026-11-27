"""The kinds of change the Activity overview counts ("What changed") and the log can filter by.

Every action the log can hold, sign-ins aside, belongs to exactly one kind; ``tests/test_activity_overview.py`` checks
that, so a new kind of entry cannot fall out of the overview unnoticed.
"""

from __future__ import annotations

from .scope import ACTION_AREAS

# Not changes: sign-ins, successful or not. Everything else a person does is a change.
SIGN_INS = frozenset(("login", "sso_login"))
NOT_CHANGES = SIGN_INS | frozenset(("login_failed", "sso_declined_attempt"))

KIND_LABELS: dict[str, str] = {
    "entries": "Entries",
    "updates": "Weekly updates and targets",
    "risks": "Risks",
    "groups": "Groups",
    "settings": "Tracker settings and roles",
    "email": "Report email",
    "people": "Users, teams and access",
    "lists": "Regions and lists",
    "other": "Other settings",
}

_UPDATES = frozenset(("inputs_saved", "targets_updated", "baseline_changed"))
_SETTINGS = frozenset(
    (
        "settings_updated",
        "tracker_created",
        "tracker_imported",
        "tracker_archived",
        "role_set",
        "role_removed",
        "tracker_team_changed",
    )
)
_EMAIL_PREFIXES = ("email_template_", "recipient_added", "recipient_removed", "report_")
_PEOPLE_AREAS = frozenset(("manage_users", "manage_teams"))
_PEOPLE_PREFIXES = ("permission_set_", "region_access_")


def kind_of(action: str) -> str:
    """The kind of change ``action`` is (``"other"`` for anything not named)."""
    if action.startswith("entry_"):
        return "entries"
    if action in _UPDATES:
        return "updates"
    if action.startswith("risk_"):
        return "risks"
    if action.startswith("group_"):
        return "groups"
    if action in _SETTINGS:
        return "settings"
    if action.startswith(_EMAIL_PREFIXES):
        return "email"
    areas = ACTION_AREAS.get(action, ())
    if _PEOPLE_AREAS.intersection(areas) or action.startswith(_PEOPLE_PREFIXES) or action == "user_admin_changed":
        return "people"
    if "manage_lists" in areas:
        return "lists"
    return "other"


# Each kind's actions, for the log's Kind filter.
KIND_ACTIONS: dict[str, frozenset[str]] = {
    key: frozenset(action for action in ACTION_AREAS if action not in NOT_CHANGES and kind_of(action) == key)
    for key in KIND_LABELS
}
