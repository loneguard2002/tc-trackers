"""The per-person limit on PDF and PNG report downloads.

Each download starts a Chromium (report/render.py), so one person may ask for at most ``EXPORTS_PER_MINUTE`` in any
minute. The count lives in the ``export_requests`` table, so every worker and instance shares it; rows older than
``KEEP_REQUESTS`` are deleted whenever a download is counted. A per-person database lock makes two downloads at the
same moment count one after the other, so the limit is exact.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import ExportRequest

EXPORTS_PER_MINUTE = 10
WINDOW = timedelta(minutes=1)
KEEP_REQUESTS = timedelta(hours=1)
LOCK_SPACE = 0x6578  # the first key of the advisory lock; the person's id is the second
LIMIT_MESSAGE = f"You have downloaded {EXPORTS_PER_MINUTE} reports in the last minute. Wait a minute, then try again."


def allow(db: Session, user_id: int) -> bool:
    """Count this download and say whether it may go ahead; one over the limit is refused and not counted. Commits."""
    db.execute(select(func.pg_advisory_xact_lock(LOCK_SPACE, user_id)))
    db.execute(delete(ExportRequest).where(ExportRequest.at <= func.now() - KEEP_REQUESTS))
    recent = db.scalar(
        select(func.count())
        .select_from(ExportRequest)
        .where(ExportRequest.user_id == user_id, ExportRequest.at > func.now() - WINDOW)
    )
    allowed = (recent or 0) < EXPORTS_PER_MINUTE
    if allowed:
        db.add(ExportRequest(user_id=user_id))
    db.commit()
    return allowed
