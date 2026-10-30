"""Guards on acting on user accounts (spec section 6.3: no account takeover; the last administrator stays).

Every user action on the Users screen asks ``account_refusal`` first, before it looks at the account's status, so a
refusal on one's own or an elevated account always gives its own message.
"""

from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..models import PermissionSetHolder, TeamMember, User

OWN_ACCOUNT_MESSAGE = "You cannot change your own account here."
ELEVATED_MESSAGE = "Only an administrator can change an administrator or a user with elevated permissions."
LAST_ADMIN_MESSAGE = "The application must keep at least one active administrator."


def is_elevated(session: Session, user: User) -> bool:
    """The administrator flag, or any permission set held directly or through any team membership.

    The account's status does not matter: a disabled former administrator is still elevated.
    """
    if user.is_admin:
        return True
    member_teams = select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    held = exists().where(or_(PermissionSetHolder.user_id == user.id, PermissionSetHolder.team_id.in_(member_teams)))
    return bool(session.scalar(select(held)))


def account_refusal(session: Session, actor: User, target: User) -> str | None:
    """Why ``actor`` may not act on ``target``, or ``None``. Administrators are never refused here."""
    if actor.is_admin:
        return None
    if target.id == actor.id:
        return OWN_ACCOUNT_MESSAGE
    if is_elevated(session, target):
        return ELEVATED_MESSAGE
    return None


def last_admin_refusal(session: Session, target: User) -> str | None:
    """``LAST_ADMIN_MESSAGE`` when ``target`` is the only active administrator, else ``None``.

    The active administrators are read ``FOR UPDATE`` (held until the caller commits or rolls back), so two
    administrators cannot disable each other, or remove each other's flag, at the same moment.
    """
    if not (target.is_admin and target.status == "active"):
        return None
    admins = session.scalars(
        select(User.id).where(User.is_admin.is_(True), User.status == "active").with_for_update()
    ).all()
    return LAST_ADMIN_MESSAGE if set(admins) <= {target.id} else None
