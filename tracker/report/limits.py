"""The per-person limit on PDF and PNG report downloads.

Each download starts a Chromium (report/render.py), so one person may ask for only a few in any minute: 10 unless an
administrator changed it on Admin › Sign-in protection (``SETTING_KEY`` in ``app_settings``, ``LOWEST`` to
``HIGHEST``). The count lives in the ``export_requests`` table, so every worker and instance shares it; rows older than
``KEEP_REQUESTS`` are deleted whenever a download is counted. A per-person database lock makes two downloads at the
same moment count one after the other, so the limit is exact.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import AppSetting, ExportRequest

SETTING_KEY = "export_downloads_per_minute"
DEFAULT_PER_MINUTE = 10
LOWEST, HIGHEST = 1, 60
FIELD = "downloads_per_minute"  # the box on Admin › Sign-in protection
WINDOW = timedelta(minutes=1)
KEEP_REQUESTS = timedelta(hours=1)
LOCK_SPACE = 0x6578  # the first key of the advisory lock; the person's id is the second


def limit_message(per_minute: int) -> str:
    reports = "report" if per_minute == 1 else "reports"
    return f"You have downloaded {per_minute} {reports} in the last minute. Wait a minute, then try again."


def load_per_minute(db: Session) -> int:
    """The saved limit; a missing or unreadable setting falls back to the default."""
    raw = db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY)) or ""
    return int(raw) if raw.isascii() and raw.isdigit() and LOWEST <= int(raw) <= HIGHEST else DEFAULT_PER_MINUTE


def parse_per_minute(raw: str | None) -> tuple[int | None, str | None]:
    """``(limit, error)`` for the text of the box."""
    text = (raw or "").strip()
    if not (text.isascii() and text.isdigit() and LOWEST <= int(text) <= HIGHEST):
        return None, f"Enter a whole number from {LOWEST} to {HIGHEST}."
    return int(text), None


def save_per_minute(db: Session, per_minute: int) -> None:
    db.merge(AppSetting(key=SETTING_KEY, value=str(per_minute)))


def allow(db: Session, user_id: int, per_minute: int) -> bool:
    """Count this download and say whether it may go ahead; one over the limit is refused and not counted. Commits."""
    db.execute(select(func.pg_advisory_xact_lock(LOCK_SPACE, user_id)))
    db.execute(delete(ExportRequest).where(ExportRequest.at <= func.now() - KEEP_REQUESTS))
    recent = db.scalar(
        select(func.count())
        .select_from(ExportRequest)
        .where(ExportRequest.user_id == user_id, ExportRequest.at > func.now() - WINDOW)
    )
    allowed = (recent or 0) < per_minute
    if allowed:
        db.add(ExportRequest(user_id=user_id))
    db.commit()
    return allowed
