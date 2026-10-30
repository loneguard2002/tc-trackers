"""Name and description checks shared by teams and permission sets.

Names are trimmed by the caller, required, at most 100 characters and unique ignoring case (a unique index on
``lower(name)`` backs the last rule, so a concurrent duplicate surfaces as an ``IntegrityError`` on commit, which the
caller turns into the same "already exists" message). Descriptions are at most 500 characters.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import PermissionSet, Team

MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


def name_error(
    session: Session, model: type[Team] | type[PermissionSet], name: str, noun: str, exclude_id: int | None = None
) -> str | None:
    """The problem with a trimmed name, or ``None``; ``exclude_id`` is the record being renamed."""
    if not name:
        return f"Enter a {noun} name."
    if len(name) > MAX_NAME_LENGTH:
        return f"A {noun} name can be at most {MAX_NAME_LENGTH} characters."
    # Postgres lowers both sides, as the unique index on lower(name) does; Python's lower() differs for some letters.
    query = select(model.id).where(func.lower(model.name) == func.lower(name))
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if session.scalar(query.limit(1)) is not None:
        return name_taken(noun)
    return None


def name_taken(noun: str) -> str:
    return f"A {noun} with that name already exists."


def description_error(description: str) -> str | None:
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return f"A description can be at most {MAX_DESCRIPTION_LENGTH} characters."
    return None
