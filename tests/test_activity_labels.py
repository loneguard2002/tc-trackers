"""Activity labels and detail description (no database)."""

import re
from pathlib import Path

from tracker.activity.labels import ACTION_LABELS, DetailLine, action_label, describe


def test_every_action_written_in_the_code_has_a_label():
    package = Path(__file__).resolve().parent.parent / "tracker"
    source = "\n".join(p.read_text(encoding="utf-8") for p in package.rglob("*.py"))
    written = set(re.findall(r'action="([a-z_]+)"', source))
    # positional helpers: _audit(db, tracker, "x", ...), _audit(tracker, "x", ...), _audit_group(db, tracker, "x", ...)
    written |= set(re.findall(r'_audit(?:_group)?\(\s*(?:[\w.()]+\s*,\s*){1,2}"([a-z_]+)"', source))
    written |= set(re.findall(r'\brecord\(\s*[\w.()]+\s*,\s*"([a-z_]+)"', source))
    assert {"group_retired", "recipient_added", "risk_deleted", "entry_created"} <= written  # the pattern works
    assert written <= set(ACTION_LABELS)
    assert {"login_failed", "entry_updated", "audit_pruned", "tracker_team_changed"} <= set(ACTION_LABELS)


def test_labels_are_sentence_case_and_unknown_actions_fall_back():
    assert action_label("login_failed") == "Failed sign-in"
    assert action_label("team_member_role_changed") == "Team member role changed"
    assert action_label("mystery") == "mystery"


def test_permission_set_entries_name_the_permissions():
    changed = describe(
        "permission_set_permissions_changed",
        {"set": "List keepers", "before": ["manage_teams"], "after": ["manage_lists", "manage_teams"]},
    )
    assert changed == [
        DetailLine("", "Manage teams", "Manage regions and lists, Manage teams", None),
        DetailLine("set", None, None, "List keepers"),
    ]
    deleted = describe("permission_set_deleted", {"name": "Old", "permissions": ["manage_lists", "retired_key"]})
    assert deleted == [
        DetailLine("name", None, None, "Old"),
        DetailLine("permissions", None, None, "Manage regions and lists, retired_key"),
    ]
    # other entries keep their values as stored
    assert describe("smtp_settings_updated", {"changed": ["manage_lists"]}) == [
        DetailLine("changed", None, None, "manage_lists")
    ]


def test_describe_reads_the_new_shape():
    assert describe("team_member_role_changed", {"team": "Windows", "before": "viewer", "after": "editor"}) == [
        DetailLine("", "viewer", "editor", None),
        DetailLine("team", None, None, "Windows"),
    ]


def test_describe_reads_older_shapes():
    assert describe("role_set", {"role": [None, "viewer"]}) == [DetailLine("role", "none", "viewer", None)]
    assert describe("user_admin_changed", {"is_admin": True}) == [DetailLine("is_admin", None, None, "Yes")]
    assert describe("login", None) == []


def test_two_item_lists_of_other_actions_stay_lists():
    assert describe("smtp_settings_updated", {"changed": ["smtp_host", "smtp_port"]}) == [
        DetailLine("changed", None, None, "smtp_host, smtp_port")
    ]
    assert describe("report_sent", {"recipients": ["a@example.com", "b@example.com"]})[0].before is None


def test_describe_lists_changed_fields_one_per_line():
    lines = describe("entry_updated", {"before": {"quantity": 12}, "after": {"quantity": 15}})
    assert lines == [DetailLine("quantity", "12", "15", None)]


def test_describe_shows_odd_values_as_text():
    assert describe("x", {"a": {"k": None, "j": False}, "b": []}) == [
        DetailLine("a", None, None, "k: none, j: No"),
        DetailLine("b", None, None, ""),
    ]
    assert describe("x", {"before": None, "after": "a"}) == [DetailLine("", "none", "a", None)]
    assert describe("x", "odd") == [DetailLine("", None, None, "odd")]
