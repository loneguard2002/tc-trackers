"""The email to the feedback address when a request is created or its sender adds a message.

Nothing here raises for a mail problem: a skipped or failed send is recorded on the request (``email_note`` and a
system message in the conversation) so that the request is never lost. The caller commits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.message import EmailMessage

from flask import current_app, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..mail import smtp
from ..mail.compose import html_to_text, sanitise_subject
from ..models import FeedbackFile, FeedbackMessage, FeedbackRequest, User
from . import service, settings

logger = logging.getLogger(__name__)

MAX_ATTACHED_BYTES = 10 * 1024 * 1024
NOTE_NO_ADDRESS = "Email not sent: no feedback address set"
NOTE_NOT_SET_UP = "Email not sent: email is not set up"
NOTE_REFUSED = "Email not sent: the mail server refused it"
TIME_FORMAT = "%d %b %Y at %H:%M UTC"
_KIND_NAMES = {"idea": "Idea", "problem": "Problem"}


def _is_first_sender_message(session: Session, request: FeedbackRequest, message: FeedbackMessage) -> bool:
    first = session.scalar(
        select(func.min(FeedbackMessage.id)).where(
            FeedbackMessage.request_id == request.id,
            FeedbackMessage.role == "sender",
            FeedbackMessage.kind == "message",
        )
    )
    return message.id == first


def _subject(session: Session, request: FeedbackRequest, message: FeedbackMessage, sender_name: str) -> str:
    if _is_first_sender_message(session, request, message):
        text = f"{_KIND_NAMES[request.kind]} from {sender_name}: {request.summary}"
    else:
        text = f"{sender_name} answered: {request.summary} ({service.reference(request.id)})"
    return sanitise_subject(text)


def _size(count: int) -> str:
    if count >= 1024 * 1024:
        return f"{count / (1024 * 1024):.1f} MB"
    return f"{max(1, round(count / 1024))} KB"


def build_email(
    session: Session, request: FeedbackRequest, message: FeedbackMessage, addresses: list[str]
) -> EmailMessage:
    """The email for one sender message: HTML with a plain-text alternative, files attached when they fit."""
    sender = session.get(User, request.sender_id) if request.sender_id else None
    sender_name = (sender.full_name if sender else "") or (sender.email if sender else "") or "Someone"
    files = list(
        session.scalars(select(FeedbackFile).where(FeedbackFile.message_id == message.id).order_by(FeedbackFile.id))
    )
    attach = sum(item.size for item in files) <= MAX_ATTACHED_BYTES
    app_url = current_app.config["APP_URL"].rstrip("/")
    page = render_template(
        "mail/feedback/new.html",
        app_url=app_url,
        kind_name=_KIND_NAMES[request.kind],
        reference=service.reference(request.id),
        summary=request.summary,
        details=message.body,
        sender_name=sender_name,
        page_title=request.page_title,
        page_link=app_url + request.page_url if request.page_url else "",
        sent=message.created_at.astimezone(timezone.utc).strftime(TIME_FORMAT),
        browser=request.browser,
        files=[(item.filename, _size(item.size)) for item in files],
        attached=attach,
        request_link=f"{app_url}/admin/feedback/{request.id}",
    )
    msg = EmailMessage()
    msg["Subject"] = _subject(session, request, message, sender_name)
    msg["To"] = ", ".join(addresses)
    if sender:
        msg["Reply-To"] = sender.email
    msg.set_content(html_to_text(page) + "\n")
    msg.add_alternative(page, subtype="html")
    if attach:
        for item in files:
            maintype, _, subtype = item.content_type.partition("/")
            msg.add_attachment(item.data, maintype=maintype, subtype=subtype, filename=item.filename)
    return msg


def _record_note(session: Session, request: FeedbackRequest, note: str) -> None:
    """Keep the note on the request and in its conversation; a clean send clears the note and adds nothing."""
    request.email_note = note
    if note:
        session.add(
            FeedbackMessage(
                request_id=request.id,
                author_id=None,
                role="system",
                kind="email",
                body=note,
                created_at=datetime.now(timezone.utc),
            )
        )


def notify_owner(session: Session, request: FeedbackRequest, message: FeedbackMessage) -> str:
    """Email the feedback address about the sender's ``message``. ``""`` when sent, else the note saying why not."""
    addresses = settings.addresses(session)
    if not addresses:
        note = NOTE_NO_ADDRESS
    else:
        config = smtp.get_smtp_config(session)
        if not (config["host"] and config["from_"]):
            note = NOTE_NOT_SET_UP
        else:
            try:
                smtp.send_message(build_email(session, request, message, addresses))
                note = ""
            except Exception:
                logger.exception("The feedback email about request %s could not be sent", request.id)
                note = NOTE_REFUSED
    _record_note(session, request, note)
    return note


NOTE_TEST_NO_ADDRESS = "Save an address first."
NOTE_TEST_NOT_SET_UP = "Email is not set up, so the test could not be sent."
NOTE_TEST_FAILED = "The test email could not be sent: the mail server refused it."


def send_test(session: Session, sender: User) -> str | None:
    """Send a sample feedback email, from ``sender``, to the saved address(es).

    ``None`` when sent, else the message to show. The sample is built, never saved, so no request is created.
    """
    to = settings.addresses(session)
    if not to:
        return NOTE_TEST_NO_ADDRESS
    config = smtp.get_smtp_config(session)
    if not (config["host"] and config["from_"]):
        return NOTE_TEST_NOT_SET_UP
    now = datetime.now(timezone.utc)
    request = FeedbackRequest(
        id=0,
        kind="idea",
        summary="Test of the feedback email",
        sender_id=sender.id,
        page_title="",
        page_url="",
        browser="",
        created_at=now,
    )
    message = FeedbackMessage(
        request_id=0,
        role="sender",
        kind="message",
        body="This is a test of the feedback email. No request was created.",
        created_at=now,
    )
    try:
        smtp.send_message(build_email(session, request, message, to))
    except Exception:
        logger.exception("The feedback test email could not be sent")
        return NOTE_TEST_FAILED
    return None
