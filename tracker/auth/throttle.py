"""The sign-in limiter: refused sign-ins counted in the ``login_failures`` table.

Two limits apply to every attempt: failures for one account (the email entered) and failures from one address (the
client's IP). Both are counted over the same window. The count lives in the database, so every Gunicorn worker and every
instance shares it, and a restart or deploy does not reset it. The time comes from the database clock, so instances with
drifting clocks still agree.

Administrators see the counts and unblock people on Admin › Sign-in protection, and change the limits there; the
limits are kept in ``app_settings``. Rows older than ``KEEP_FAILURES`` are deleted whenever a new failure is recorded.

The failure that brings a count to its limit starts a block: ``fail`` says so, and ``record_block`` writes it to the
activity log. The count beside Sign-in protection in the menu is the blocks started since anyone last opened
the page (``SEEN_KEY``, shared by everyone who can open it), like the New count beside Feedback, so a block that has
already ended is not missed.

``fail``, ``clear`` and ``save_limits`` only add to the caller's transaction; the caller commits. Two attempts at the
same moment can both pass the check: the limit is a brake on guessing, not an exact count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..audit import record
from ..models import AppSetting, AuditLog, LoginFailure

KINDS = ("account", "address")
KEEP_FAILURES = timedelta(days=1)
MAX_VALUE_LENGTH = 254  # the longest email kept; an address is far shorter
EMAIL_KEY = "login_block_email"  # "off" when administrators asked not to be emailed about blocks
SEEN_KEY = "login_blocks_seen_at"  # when an administrator last opened Sign-in protection (UTC, ISO 8601)
BLOCKED_ACTION = "sign_in_blocked"

# (setting key, default, lowest, highest) for each limit an administrator can change.
LIMIT_FIELDS = {
    "account_attempts": ("login_account_attempts", 5, 3, 50),
    "address_attempts": ("login_address_attempts", 20, 5, 500),
    "window_minutes": ("login_window_minutes", 5, 1, 60),
}


@dataclass(frozen=True)
class Limits:
    account_attempts: int = 5
    address_attempts: int = 20
    window_minutes: int = 5
    email_admins: bool = True  # email the people who manage sign-in protection when a block starts

    @property
    def window(self) -> timedelta:
        return timedelta(minutes=self.window_minutes)

    def attempts(self, kind: str) -> int:
        return self.account_attempts if kind == "account" else self.address_attempts

    def as_dict(self) -> dict[str, int | bool]:
        return {name: getattr(self, name) for name in (*LIMIT_FIELDS, "email_admins")}

    def form(self) -> dict[str, str]:
        """The values as the settings form shows them: numbers as text, the checkbox as "on" or ""."""
        return {
            **{name: str(getattr(self, name)) for name in LIMIT_FIELDS},
            "email_admins": "on" if self.email_admins else "",
        }


@dataclass(frozen=True)
class FailureSummary:
    """One account or address with failures in the last day, as Admin › Sign-in protection lists it."""

    kind: str
    value: str
    last_day: int  # failures in the last ``KEEP_FAILURES``
    in_window: int  # failures inside the current window: the number the limit is compared with
    limit: int
    last_at: datetime
    unblocks_at: datetime | None  # when the count falls below the limit; None when not blocked

    @property
    def blocked(self) -> bool:
        return self.unblocks_at is not None

    @property
    def left(self) -> int:
        return max(self.limit - self.in_window, 0)


def load_limits(db: Session) -> Limits:
    """The saved limits; a missing or unreadable setting falls back to its default."""
    keys = [key for key, *_ in LIMIT_FIELDS.values()] + [EMAIL_KEY]
    stored = dict(db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys))).all())
    values = {}
    for name, (key, default, low, high) in LIMIT_FIELDS.items():
        raw = stored.get(key, "")
        values[name] = int(raw) if raw.isascii() and raw.isdigit() and low <= int(raw) <= high else default
    return Limits(**values, email_admins=stored.get(EMAIL_KEY) != "off")


def parse_limits(form) -> tuple[Limits | None, dict[str, str]]:
    """``(limits, errors)`` from the submitted form; ``errors`` maps a field name to its message."""
    values: dict[str, int] = {}
    errors: dict[str, str] = {}
    for name, (_key, _default, low, high) in LIMIT_FIELDS.items():
        raw = (form.get(name) or "").strip()
        if not (raw.isascii() and raw.isdigit() and low <= int(raw) <= high):
            errors[name] = f"Enter a whole number from {low} to {high}."
        else:
            values[name] = int(raw)
    return (None, errors) if errors else (Limits(**values, email_admins=form.get("email_admins") == "on"), {})


def save_limits(db: Session, limits: Limits) -> None:
    for name, (key, *_rest) in LIMIT_FIELDS.items():
        db.merge(AppSetting(key=key, value=str(getattr(limits, name))))
    db.merge(AppSetting(key=EMAIL_KEY, value="on" if limits.email_admins else "off"))


def _value(value: str | None) -> str:
    return (value or "")[:MAX_VALUE_LENGTH]


def _in_window(db: Session, limits: Limits, kind: str, value: str | None) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(LoginFailure)
            .where(
                LoginFailure.kind == kind,
                LoginFailure.value == _value(value),
                LoginFailure.at > func.now() - limits.window,
            )
        )
        or 0
    )


def blocked(db: Session, limits: Limits, kind: str, value: str | None) -> bool:
    return _in_window(db, limits, kind, value) >= limits.attempts(kind)


def fail(db: Session, limits: Limits, kind: str, value: str | None) -> bool:
    """Count one failure; ``True`` when it brings the count to the limit, so a block starts now."""
    db.execute(delete(LoginFailure).where(LoginFailure.at <= func.now() - KEEP_FAILURES))
    db.add(LoginFailure(kind=kind, value=_value(value)))
    db.flush()
    return _in_window(db, limits, kind, value) == limits.attempts(kind)


def record_block(db: Session, limits: Limits, kind: str, value: str | None) -> None:
    """Write a block that has just started to the activity log; the caller commits."""
    record(
        db,
        user_id=None,
        tracker_id=None,
        action=BLOCKED_ACTION,
        entity="login_failures",
        entity_id=kind,
        detail={kind: _value(value), "failures": limits.attempts(kind), "window_minutes": limits.window_minutes},
    )


def seen_at(db: Session) -> datetime | None:
    """When an administrator last opened Sign-in protection; ``None`` before the first time."""
    raw = db.scalar(select(AppSetting.value).where(AppSetting.key == SEEN_KEY))
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def mark_seen(db: Session, now: datetime) -> None:
    db.merge(AppSetting(key=SEEN_KEY, value=now.astimezone(timezone.utc).isoformat()))


def new_blocks(db: Session, since: datetime | None) -> set[tuple[str, str]]:
    """``(kind, value)`` of every account and address whose block started after ``since`` (all of them when
    ``None``), from the activity log."""
    query = select(AuditLog.entity_id, AuditLog.detail).where(AuditLog.action == BLOCKED_ACTION)
    if since is not None:
        query = query.where(AuditLog.at > since)
    return {(kind, (detail or {}).get(kind, "")) for kind, detail in db.execute(query)}


def new_block_count(db: Session) -> int:
    """The number beside Sign-in protection in the menu: accounts and addresses blocked since the page was last
    opened."""
    return len(new_blocks(db, seen_at(db)))


def clear(db: Session, kind: str, value: str | None) -> int:
    """Forget every failure of this account or address; the number removed."""
    return db.execute(
        delete(LoginFailure).where(LoginFailure.kind == kind, LoginFailure.value == _value(value))
    ).rowcount


def blocked_count(db: Session, limits: Limits) -> int:
    """How many accounts and addresses are blocked now."""
    groups = (
        select(LoginFailure.kind, LoginFailure.value, func.count().label("n"))
        .where(LoginFailure.at > func.now() - limits.window)
        .group_by(LoginFailure.kind, LoginFailure.value)
        .subquery()
    )
    over = or_(
        and_(groups.c.kind == "account", groups.c.n >= limits.account_attempts),
        and_(groups.c.kind == "address", groups.c.n >= limits.address_attempts),
    )
    return db.scalar(select(func.count()).select_from(groups).where(over)) or 0


def summaries(db: Session, limits: Limits) -> tuple[datetime, list[FailureSummary]]:
    """``(now, rows)``: every account and address with a failure in the last day, blocked ones first, then the most
    recent failure first. ``now`` is the database clock the counts were taken with."""
    now = db.scalar(select(func.now()))
    since = now - limits.window
    found: dict[tuple[str, str], list[datetime]] = {}
    for kind, value, at in db.execute(
        select(LoginFailure.kind, LoginFailure.value, LoginFailure.at)
        .where(LoginFailure.at > now - KEEP_FAILURES)
        .order_by(LoginFailure.at)
    ):
        found.setdefault((kind, value), []).append(at)
    rows = []
    for (kind, value), times in found.items():
        recent = [at for at in times if at > since]
        limit = limits.attempts(kind)
        # Blocked until enough of the recent failures leave the window to bring the count below the limit.
        unblocks_at = recent[len(recent) - limit] + limits.window if len(recent) >= limit else None
        rows.append(FailureSummary(kind, value, len(times), len(recent), limit, times[-1], unblocks_at))
    rows.sort(key=lambda row: (not row.blocked, -row.last_at.timestamp(), row.kind, row.value))
    return now, rows
