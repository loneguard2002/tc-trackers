"""Feedback requests: the rules for creating, answering and closing them (see the feedback spec).

Nothing here commits; the caller does. Every function that changes a request bumps ``last_activity_at`` and records
an Activity entry that names the reference, kind, action and status change, and never the summary, text or file names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, object_session
from werkzeug.datastructures import FileStorage

from ..audit import record
from ..models import FeedbackFile, FeedbackMessage, FeedbackRequest, User

STATUSES = ("new", "under_review", "waiting", "planned", "done", "will_not_do", "withdrawn")
STATUS_LABELS = (
    "New",
    "Under review",
    "Waiting for an answer",
    "Planned",
    "Done",
    "Will not do",
    "Withdrawn",
)
OPEN = STATUSES[:4]
CLOSED = STATUSES[4:]

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
_REVIEWER_KINDS = ("update", "question", "status")


def reference(request_id: int) -> str:
    """``FB-0042``: the id padded to four digits (longer ids are written in full)."""
    return f"FB-{request_id:04d}"


def _now() -> datetime:
    # A transaction's ``now()`` does not move, and the order of events on a request matters; so time is read here.
    return datetime.now(timezone.utc)


# ---- files --------------------------------------------------------------------------------------------------------


@dataclass
class ValidFile:
    filename: str
    content_type: str
    data: bytes


_PICTURES = {
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/gif": (".gif",),
    "image/webp": (".webp",),
}
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ZIP_TYPES = {".docx": _DOCX, ".xlsx": _XLSX}
_TEXT_TYPES = {".txt": "text/plain", ".csv": "text/csv"}


def _content_type(name: str, data: bytes) -> str | None:
    """The type of a file by its content, if it is allowed and its name agrees; ``None`` otherwise."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        found = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        found = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        found = "image/gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        found = "image/webp"
    elif data.startswith(b"%PDF-"):
        return "application/pdf" if ext == ".pdf" else None
    elif data.startswith(b"PK\x03\x04"):
        return _ZIP_TYPES.get(ext)
    elif ext in _TEXT_TYPES:
        head = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
        if b"\x00" in data or head.startswith(b"<") or b"<svg" in head or b"<html" in head:
            return None
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return _TEXT_TYPES[ext]
    else:
        return None
    return found if ext in _PICTURES[found] else None


def check_files(files: list[FileStorage]) -> tuple[list[ValidFile], list[str]]:
    """The files that may be kept, and the reasons for any that may not. Any reason means nothing should be saved."""
    given = [f for f in files if f and (f.filename or "")]
    if len(given) > MAX_FILES:
        return [], ["Attach at most 5 files."]
    valid: list[ValidFile] = []
    errors: list[str] = []
    for item in given:
        name = (item.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:200]
        data = item.stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            errors.append(f"{name} is over 5 MB.")
            continue
        content_type = _content_type(name, data)
        if content_type is None:
            errors.append(f"{name} is not a picture, PDF, Word, Excel or text file.")
            continue
        valid.append(ValidFile(name, content_type, data))
    return (valid, []) if not errors else ([], errors)


# ---- requests -----------------------------------------------------------------------------------------------------


def _add_message(
    session: Session,
    request: FeedbackRequest,
    *,
    author_id: int | None,
    role: str,
    kind: str,
    body: str = "",
    status_from: str | None = None,
    status_to: str | None = None,
    files: list[ValidFile] | None = None,
) -> FeedbackMessage:
    now = _now()
    message = FeedbackMessage(
        request_id=request.id,
        author_id=author_id,
        role=role,
        kind=kind,
        body=body,
        status_from=status_from,
        status_to=status_to,
        created_at=now,
    )
    session.add(message)
    session.flush()
    for item in files or []:
        session.add(
            FeedbackFile(
                request_id=request.id,
                message_id=message.id,
                filename=item.filename,
                content_type=item.content_type,
                size=len(item.data),
                data=item.data,
                created_at=now,
            )
        )
    request.last_activity_at = now
    return message


def _record(session: Session, request: FeedbackRequest, user_id: int | None, action: str, **detail: str) -> None:
    session.flush()
    record(
        session,
        user_id=user_id,
        tracker_id=None,
        action=action,
        entity="feedback",
        entity_id=request.id,
        detail={"reference": reference(request.id), "kind": request.kind, **detail},
    )


def _status_detail(before: str, after: str) -> dict[str, str]:
    return {"before": before, "after": after}


def create_request(
    session: Session,
    sender: User,
    kind: str,
    summary: str,
    details: str,
    page_title: str,
    page_url: str,
    browser: str,
    files: list[ValidFile],
) -> FeedbackRequest:
    now = _now()
    request = FeedbackRequest(
        kind=kind,
        summary=summary,
        details=details,
        status="new",
        sender_id=sender.id,
        page_title=page_title,
        page_url=page_url,
        browser=browser,
        created_at=now,
        last_activity_at=now,
    )
    session.add(request)
    session.flush()
    _add_message(session, request, author_id=sender.id, role="sender", kind="message", body=details, files=files)
    _record(session, request, sender.id, "feedback_sent")
    return request


def reviewer_reply(
    session: Session,
    request: FeedbackRequest,
    author: User,
    kind: Literal["update", "question"],
    body: str,
    files: list[ValidFile],
) -> FeedbackMessage:
    """A reviewer's update or question, on any request. A question sets the status to Waiting for an answer."""
    if kind not in ("update", "question"):
        raise ValueError(kind)
    message = _add_message(session, request, author_id=author.id, role="reviewer", kind=kind, body=body, files=files)
    detail: dict[str, str] = {"reply": kind}
    if kind == "question" and request.status != "waiting":
        detail.update(_status_detail(request.status, "waiting"))
        request.status = "waiting"
    _record(session, request, author.id, "feedback_replied", **detail)
    return message


def set_status(session: Session, request: FeedbackRequest, author: User, status: str) -> None:
    """Change the status, on any request, and note it in the conversation. The same status changes nothing."""
    if status not in STATUSES:
        raise ValueError(status)
    if status == request.status:
        return
    before = request.status
    request.status = status
    _add_message(
        session, request, author_id=author.id, role="reviewer", kind="status", status_from=before, status_to=status
    )
    _record(session, request, author.id, "feedback_status", **_status_detail(before, status))


def sender_message(session: Session, request: FeedbackRequest, body: str, files: list[ValidFile]) -> FeedbackMessage:
    """The sender's answer or added message on an open request; Waiting for an answer moves to Under review."""
    if request.status in CLOSED:
        raise ValueError("A closed request cannot be added to.")
    message = _add_message(
        session, request, author_id=request.sender_id, role="sender", kind="message", body=body, files=files
    )
    detail: dict[str, str] = {}
    if request.status == "waiting":
        detail = _status_detail("waiting", "under_review")
        request.status = "under_review"
    _record(session, request, request.sender_id, "feedback_answered", **detail)
    return message


def withdraw(session: Session, request: FeedbackRequest) -> None:
    if request.status in CLOSED:
        raise ValueError("A closed request cannot be withdrawn.")
    before = request.status
    request.status = "withdrawn"
    _add_message(
        session, request, author_id=request.sender_id, role="sender", kind="status", status_from=before,
        status_to="withdrawn",
    )  # fmt: skip
    _record(session, request, request.sender_id, "feedback_withdrawn", **_status_detail(before, "withdrawn"))


# ---- what the sender has seen -------------------------------------------------------------------------------------


def mark_seen(session: Session, request: FeedbackRequest) -> None:
    """The sender opened the request; opening is not activity, so ``last_activity_at`` stays."""
    request.sender_seen_at = _now()


def _unseen_reply():
    """A condition: some reviewer update, question or status change came after the sender last opened the request."""
    return exists().where(
        FeedbackMessage.request_id == FeedbackRequest.id,
        FeedbackMessage.role == "reviewer",
        FeedbackMessage.kind.in_(_REVIEWER_KINDS),
        (FeedbackRequest.sender_seen_at.is_(None)) | (FeedbackMessage.created_at > FeedbackRequest.sender_seen_at),
    )


def has_new_reply(request: FeedbackRequest) -> bool:
    session = object_session(request)
    return bool(session.scalar(select(_unseen_reply()).where(FeedbackRequest.id == request.id)))


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(FeedbackRequest).where(FeedbackRequest.sender_id == user_id, _unseen_reply())
    )


def new_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(FeedbackRequest).where(FeedbackRequest.status == "new"))


def replies(request: FeedbackRequest) -> int:
    """The reviewers' updates and questions on the request."""
    return object_session(request).scalar(
        select(func.count())
        .select_from(FeedbackMessage)
        .where(FeedbackMessage.request_id == request.id, FeedbackMessage.kind.in_(("update", "question")))
    )
