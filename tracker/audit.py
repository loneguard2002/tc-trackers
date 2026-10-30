"""Audit log helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog

NO_CHANGES_MESSAGE = "No changes to save."  # the answer to a save that changes nothing; it writes no entry


def record(
    session: Session,
    *,
    user_id: int | None,
    tracker_id: int | None,
    action: str,
    entity: str,
    entity_id: str | int | None,
    detail: dict | None = None,
    target_user_id: int | None = None,
) -> None:
    """Add an audit row to the session; the caller commits."""
    session.add(
        AuditLog(
            user_id=user_id,
            tracker_id=tracker_id,
            action=action,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            detail=detail,
            target_user_id=target_user_id,
        )
    )


def change(before: object, after: object) -> dict:
    """The detail payload of a change entry."""
    return {"before": before, "after": after}
