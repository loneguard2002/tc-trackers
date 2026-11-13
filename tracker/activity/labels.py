"""Readable action labels and before/after descriptions of stored activity details (spec section 8.1).

Old entries keep their stored shapes: the oldest changes store ``{field: [before, after]}``, newer ones
``{"before": ..., "after": ...}``. Nothing here fails on a shape it does not know.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from ..auth.permissions import PERMISSIONS

ACTION_LABELS: dict[str, str] = {
    "login": "Signed in",
    "sso_login": "Signed in with Microsoft",
    "sso_linked": "Microsoft account linked",
    "login_failed": "Failed sign-in",
    "user_created": "User created",
    "user_approved": "User approved",
    "user_disabled": "User disabled",
    "user_enabled": "User enabled",
    "password_reset": "Password reset",
    "user_admin_changed": "Administrator flag changed",
    "user_name_synced": "User name updated from Microsoft",
    "team_created": "Team created",
    "team_renamed": "Team details changed",
    "team_moved": "Team moved",
    "team_parent_added": "Higher team added",
    "team_parent_removed": "Higher team removed",
    "team_deleted": "Team deleted",
    "team_member_added": "Team member added",
    "team_member_role_changed": "Team member role changed",
    "team_member_removed": "Team member removed",
    "region_created": "Region added",
    "region_changed": "Region changed",
    "region_retired": "Region retired",
    "region_restored": "Region restored",
    "region_deleted": "Region deleted",
    "region_access_given": "Region access given",
    "region_access_changed": "Region access changed",
    "region_access_removed": "Region access removed",
    "location_created": "Location added",
    "location_changed": "Location changed",
    "location_retired": "Location retired",
    "location_restored": "Location restored",
    "location_deleted": "Location deleted",
    "business_line_created": "Business line added",
    "business_line_changed": "Business line changed",
    "business_line_retired": "Business line retired",
    "business_line_restored": "Business line restored",
    "business_line_deleted": "Business line deleted",
    "tracker_created": "Tracker created",
    "tracker_imported": "Tracker imported",
    "tracker_archived": "Tracker archived",
    "settings_updated": "Tracker settings updated",
    "tracker_team_changed": "Tracker team changed",
    "role_set": "Tracker role set",
    "role_removed": "Tracker role removed",
    "group_created": "Group created",
    "group_updated": "Group updated",
    "group_deleted": "Group deleted",
    "group_retired": "Group retired",
    "group_unretired": "Group restored",
    "group_reordered": "Groups reordered",
    "baseline_changed": "Baseline changed",
    "entry_created": "Entry created",
    "entry_updated": "Entry updated",
    "entry_deleted": "Entry deleted",
    "targets_updated": "Targets updated",
    "inputs_saved": "Inputs saved",
    "risk_created": "Risk created",
    "risk_updated": "Risk updated",
    "risk_deleted": "Risk deleted",
    "recipient_added": "Recipient added",
    "recipient_removed": "Recipient removed",
    "email_template_saved": "Email template saved",
    "email_template_reset": "Email template reset",
    "report_sent": "Report sent",
    "report_send_queued": "Report send queued",
    "report_send_failed": "Report send failed",
    "report_reminder_sent": "Update reminder sent",
    "report_test_sent": "Test report sent",
    "permission_set_created": "Permission set created",
    "permission_set_renamed": "Permission set renamed",
    "permission_set_deleted": "Permission set deleted",
    "permission_set_permissions_changed": "Permission set permissions changed",
    "permission_set_holder_added": "Permission set holder added",
    "permission_set_holder_removed": "Permission set holder removed",
    "smtp_settings_updated": "Email settings updated",
    "audit_retention_changed": "Activity retention changed",
    "audit_pruned": "Old activity entries removed",
}

# The older actions that store each change as {field: [before, after]}.
LEGACY_PAIR_ACTIONS = frozenset(
    {
        "role_set",
        "role_removed",
        "settings_updated",
        "group_updated",
        "baseline_changed",
        "targets_updated",
        "inputs_saved",
        "risk_updated",
    }
)


# Entries whose detail lists permissions: shown by name ("Manage regions and lists"), not by the stored key.
PERMISSION_DETAIL_KEYS = {
    "permission_set_permissions_changed": ("before", "after"),
    "permission_set_deleted": ("permissions",),
}


def _permission_names(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [PERMISSIONS[item][0] if isinstance(item, str) and item in PERMISSIONS else item for item in value]
    return value


class DetailLine(NamedTuple):
    """One line of an entry's detail: a change (``before``/``after``) or a plain ``value``; ``field`` may be empty."""

    field: str
    before: str | None
    after: str | None
    value: str | None


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def _text(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value)
    return str(value)


def describe(action: str, detail: Any) -> list[DetailLine]:
    """The detail of an entry as lines; ``None`` gives no lines."""
    if detail is None:
        return []
    if not isinstance(detail, dict):
        return [DetailLine("", None, None, _text(detail))]
    keys = PERMISSION_DETAIL_KEYS.get(action, ())
    detail = {key: _permission_names(value) if key in keys else value for key, value in detail.items()}
    lines: list[DetailLine] = []
    if "before" in detail or "after" in detail:
        before, after = detail.get("before"), detail.get("after")
        if isinstance(before, dict) and isinstance(after, dict):
            for key in [*before, *(k for k in after if k not in before)]:
                lines.append(DetailLine(str(key), _text(before.get(key)), _text(after.get(key)), None))
        else:
            lines.append(DetailLine("", _text(before), _text(after), None))
    for key, value in detail.items():
        if key in ("before", "after"):
            continue
        if action in LEGACY_PAIR_ACTIONS and isinstance(value, (list, tuple)) and len(value) == 2:
            lines.append(DetailLine(str(key), _text(value[0]), _text(value[1]), None))
        else:
            lines.append(DetailLine(str(key), None, None, _text(value)))
    return lines
