"""Guards on acting on user accounts (spec section 6.3: no account takeover; the last administrator stays).

Every user action on the Users screen asks ``account_refusal`` first, before it looks at the account's status, so a
refusal on one's own or an elevated account always gives its own message. ``vouched_refusal`` closes the stand-in
account route: a non-administrator who created an account or set its password, and so may know that password, cannot
also give the account access to trackers.
"""

from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..models import AuditLog, PermissionSetHolder, TeamMember, User

OWN_ACCOUNT_MESSAGE = "You cannot change your own account here."
ELEVATED_MESSAGE = "Only an administrator can change an administrator or a user with elevated permissions."
LAST_ADMIN_MESSAGE = "The application must keep at least one active administrator."
LAST_PASSWORD_ADMIN_MESSAGE = (
    "Keep at least one administrator who signs in with a password, in case Microsoft sign-in stops working."
)
VOUCHED_MESSAGE = "You created this account or set its password, so another person must give it access."
VOUCHED_ACTIONS = ("user_created", "password_reset")


def find_by_email(session: Session, email: str) -> User | None:
    """The account with this email, already lower case, whose status is not ``deleted``, or ``None``.

    A deleted person keeps their row and their email, so every lookup of a person by email goes through here.
    """
    return session.scalar(select(User).where(User.email == email, User.status != "deleted"))


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


def vouched_refusal(session: Session, actor: User, target: User) -> str | None:
    """``VOUCHED_MESSAGE`` when a non-administrator ``actor`` created ``target`` or reset its password, else ``None``.

    Asked before giving access (a team place, a member role, a direct tracker role). The activity log is the record:
    an entry removed by the retention period no longer counts.
    """
    if actor.is_admin:
        return None
    vouched = exists().where(
        AuditLog.action.in_(VOUCHED_ACTIONS),
        AuditLog.user_id == actor.id,
        AuditLog.target_user_id == target.id,
    )
    return VOUCHED_MESSAGE if session.scalar(select(vouched)) else None


def _lock_active_admins(session: Session) -> dict[int, str]:
    """Each active administrator's id with their ``auth_source``, read ``FOR UPDATE`` (held until the caller ends).

    The caller's transaction holds the locks until it commits or rolls back, so two administrators cannot disable each
    other, or remove each other's flag, at the same moment.
    """
    rows = session.execute(
        select(User.id, User.auth_source)
        .where(User.is_admin.is_(True), User.status == "active")
        .order_by(User.id)  # one lock order, so two of these cannot deadlock
        .with_for_update()
    ).all()
    return dict(rows)


def last_admin_refusal(session: Session, target: User) -> str | None:
    """``LAST_ADMIN_MESSAGE`` when ``target`` is the only active administrator, else ``None``.

    The active administrators are locked (see ``_lock_active_admins``).
    """
    if not (target.is_admin and target.status == "active"):
        return None
    return LAST_ADMIN_MESSAGE if set(_lock_active_admins(session)) <= {target.id} else None


def last_password_admin_refusal(session: Session, target: User) -> str | None:
    """``LAST_PASSWORD_ADMIN_MESSAGE`` when ``target`` is the only active administrator who signs in with a password.

    Asked only while Microsoft sign-in is on, before an account stops being an active administrator who signs in with
    a password: a Microsoft sign-in failure must never lock out every administrator. The active administrators are
    locked as ``last_admin_refusal`` does.
    """
    if not (target.is_admin and target.status == "active" and target.auth_source == "local"):
        return None
    admins = _lock_active_admins(session)
    others = any(source == "local" for admin_id, source in admins.items() if admin_id != target.id)
    return None if others else LAST_PASSWORD_ADMIN_MESSAGE
