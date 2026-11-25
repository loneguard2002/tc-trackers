"""The sign-in limiter: refused sign-ins counted in the ``login_failures`` table.

Two limits apply to every attempt: failures for one account (the email entered) and failures from one address (the
client's IP). Both are counted over the same window. The count lives in the database, so every Gunicorn worker and every
instance shares it, and a restart or deploy does not reset it. The time comes from the database clock, so instances with
drifting clocks still agree.

Administrators see the counts and unblock people on Admin › Sign-in protection, and change the limits there; the
limits are kept in ``app_settings``. Rows older than ``KEEP_FAILURES`` are deleted whenever a new failure is recorded.

``fail``, ``clear`` and ``save_limits`` only add to the caller's transaction; the caller commits. Two attempts at the
same moment can both pass the check: the limit is a brake on guessing, not an exact count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..models import AppSetting, LoginFailure

KINDS = ("account", "address")
KEEP_FAILURES = timedelta(days=1)
MAX_VALUE_LENGTH = 254  # the longest email kept; an address is far shorter

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

    @property
    def window(self) -> timedelta:
        return timedelta(minutes=self.window_minutes)

    def attempts(self, kind: str) -> int:
        return self.account_attempts if kind == "account" else self.address_attempts

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in LIMIT_FIELDS}


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
    keys = [key for key, *_ in LIMIT_FIELDS.values()]
    stored = dict(db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys))).all())
    values = {}
    for name, (key, default, low, high) in LIMIT_FIELDS.items():
        raw = stored.get(key, "")
        values[name] = int(raw) if raw.isascii() and raw.isdigit() and low <= int(raw) <= high else default
    return Limits(**values)


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
    return (None, errors) if errors else (Limits(**values), {})


def save_limits(db: Session, limits: Limits) -> None:
    for name, (key, *_rest) in LIMIT_FIELDS.items():
        db.merge(AppSetting(key=key, value=str(getattr(limits, name))))


def _value(value: str | None) -> str:
    return (value or "")[:MAX_VALUE_LENGTH]


def blocked(db: Session, limits: Limits, kind: str, value: str | None) -> bool:
    recent = db.scalar(
        select(func.count())
        .select_from(LoginFailure)
        .where(
            LoginFailure.kind == kind,
            LoginFailure.value == _value(value),
            LoginFailure.at > func.now() - limits.window,
        )
    )
    return (recent or 0) >= limits.attempts(kind)


def fail(db: Session, kind: str, value: str | None) -> None:
    db.execute(delete(LoginFailure).where(LoginFailure.at <= func.now() - KEEP_FAILURES))
    db.add(LoginFailure(kind=kind, value=_value(value)))
    db.flush()


def clear(db: Session, kind: str, value: str | None) -> int:
    """Forget every failure of this account or address; the number removed."""
    return db.execute(
        delete(LoginFailure).where(LoginFailure.kind == kind, LoginFailure.value == _value(value))
    ).rowcount


def blocked_count(db: Session, limits: Limits) -> int:
    """How many accounts and addresses are blocked now, for the count beside Sign-in protection in the menu."""
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
