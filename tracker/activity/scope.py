"""Which Activity entries a person sees (the owner's rule, 26 Nov 2026).

Administrators see every entry. Everyone else (with "View activity", which opens the page) sees their own actions,
the entries about trackers they have a role on, and the entries of each area they manage:

| Area | Seen by |
|---|---|
| a tracker: entries, risks, settings, roles, the report email | a role on that tracker |
| users and sign-in | Manage users |
| teams and team roles | Manage teams |
| regions, locations, business lines | Manage regions and lists |
| email settings | Manage email settings |
| feedback | Manage feedback |
| sign-in protection | Manage sign-in protection |
| permission sets, the administrator flag, region access, the activity log itself | administrators only |

``ACTION_AREAS`` names the area (or areas) of every action; ``tests/test_activity_scope.py`` requires every action
the log can hold to be listed, so a new kind of entry cannot appear to everyone unnoticed.
"""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from ..models import AuditLog, User

TRACKER = "tracker"  # seen with a role on the entry's tracker
ADMIN = "admin"  # administrators only

_TRACKER = (TRACKER,)
_USERS = ("manage_users",)

ACTION_AREAS: dict[str, tuple[str, ...]] = {
    # A tracker's own work and settings.
    **dict.fromkeys(
        (
            "baseline_changed",
            "email_template_reset",
            "email_template_saved",
            "entry_created",
            "entry_deleted",
            "entry_updated",
            "group_created",
            "group_deleted",
            "group_reordered",
            "group_retired",
            "group_unretired",
            "group_updated",
            "inputs_saved",
            "recipient_added",
            "recipient_removed",
            "report_reminder_sent",
            "report_send_failed",
            "report_send_queued",
            "report_sent",
            "report_test_sent",
            "risk_created",
            "risk_deleted",
            "risk_updated",
            "settings_updated",
            "targets_updated",
            "tracker_archived",
            "tracker_created",
            "tracker_imported",
            # Who can open a tracker: for its own people only, not for those who hand out roles (the owner's ruling).
            "role_set",
            "role_removed",
            "tracker_team_changed",
        ),
        _TRACKER,
    ),
    # Users and sign-in.
    **dict.fromkeys(
        (
            "access_email_sent",
            "access_reminder_sent",
            "login",
            "login_failed",
            "password_reset",
            "sign_in_switched",
            "sso_declined_attempt",
            "sso_linked",
            "sso_login",
            "user_approved",
            "user_created",
            "user_declined",
            "user_deleted",
            "user_disabled",
            "user_enabled",
            "user_name_synced",
            "user_sessions_ended",
        ),
        _USERS,
    ),
    # Sign-in protection.
    **dict.fromkeys(
        (
            "download_limit_changed",
            "sign_in_alert_sent",
            "sign_in_blocked",
            "sign_in_limits_changed",
            "sign_in_unblocked",
        ),
        ("manage_sign_in_protection",),
    ),
    # Teams.
    **dict.fromkeys(
        (
            "team_created",
            "team_deleted",
            "team_member_added",
            "team_member_removed",
            "team_member_role_changed",
            "team_moved",
            "team_parent_added",
            "team_parent_removed",
            "team_renamed",
        ),
        ("manage_teams",),
    ),
    # Regions, locations and business lines.
    **dict.fromkeys(
        (
            "business_line_changed",
            "business_line_created",
            "business_line_deleted",
            "business_line_restored",
            "business_line_retired",
            "location_changed",
            "location_created",
            "location_deleted",
            "location_restored",
            "location_retired",
            "region_changed",
            "region_created",
            "region_deleted",
            "region_restored",
            "region_retired",
        ),
        ("manage_lists",),
    ),
    # Email settings.
    "smtp_settings_updated": ("manage_email_settings",),
    "feedback_settings_changed": ("manage_email_settings",),
    # Feedback.
    **dict.fromkeys(
        ("feedback_answered", "feedback_replied", "feedback_sent", "feedback_status", "feedback_withdrawn"),
        ("manage_feedback",),
    ),
    # Administrators only.
    **dict.fromkeys(
        (
            "audit_pruned",
            "audit_retention_changed",
            "permission_set_created",
            "permission_set_deleted",
            "permission_set_holder_added",
            "permission_set_holder_removed",
            "permission_set_permissions_changed",
            "permission_set_renamed",
            "region_access_changed",
            "region_access_given",
            "region_access_removed",
            "user_admin_changed",
        ),
        (ADMIN,),
    ),
}


def visible_actions(held: frozenset[str], has_trackers: bool) -> set[str]:
    """The actions whose entries the person can see in at least one place (their own actions aside)."""
    return {
        action
        for action, areas in ACTION_AREAS.items()
        if any((area == TRACKER and has_trackers) or area in held for area in areas)
    }


def visible_entries(viewer: User, held: frozenset[str], can_open: dict[int, str] | None) -> ColumnElement | None:
    """The condition limiting Activity to what ``viewer`` may see, or ``None`` for an administrator (everything).

    ``held`` is the viewer's permissions and ``can_open`` their tracker roles (tracker id to role). An entry about a
    tracker shows only for that tracker's people (an entry whose tracker has since been deleted, for administrators
    only); an area's entries show to those who manage it; the viewer's own actions always show.
    """
    if viewer.is_admin or can_open is None:
        return None
    parts: list[ColumnElement] = [AuditLog.user_id == viewer.id]
    tracker_actions = [action for action, areas in ACTION_AREAS.items() if TRACKER in areas]
    if can_open:
        parts.append(and_(AuditLog.action.in_(tracker_actions), AuditLog.tracker_id.in_(list(can_open))))
    managed = sorted(action for action, areas in ACTION_AREAS.items() if any(area in held for area in areas))
    if managed:
        parts.append(AuditLog.action.in_(managed))
    return or_(*parts)
