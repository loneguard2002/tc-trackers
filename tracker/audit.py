"""Audit log helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    session: Session,
    *,
    user_id: int | None,
    tracker_id: int | None,
    action: str,
    entity: str,
    entity_id: str | int | None,
    detail: dict | None = None,
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
        )
    )
