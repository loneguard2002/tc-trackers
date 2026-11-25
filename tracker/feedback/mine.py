"""My feedback: the sender's side. The list of their own requests, a request in the right-hand panel or on its own page
(where the reply email's link leads), an answer or added message, and Withdraw.

A request is the sender's alone here: anyone else, reviewers included, gets 404 (reviewers use Admin › Feedback).
Opening a request marks it seen, which clears its "New reply" mark.
"""

from __future__ import annotations

from datetime import timezone

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..auth import current_user, login_required
from ..db import get_session
from ..ids import in_range
from ..models import FeedbackRequest
from . import bp, mail, service
from .views import (
    DETAILS_TOO_LONG,
    KIND_LABELS,
    MAX_REPLY,
    STATUS_NAMES,
    _from_panel,
    _request_context,
    _when,
)

ANSWER_REQUIRED = "Write your answer."
MESSAGE_REQUIRED = "Write your message."
CLOSED_NOTICE = "This request is closed, so it cannot be changed."
STATUS_FILTERS = (("open", "Open"), ("closed", "Closed"), ("all", "All"))


def _mine_or_404(request_id: int) -> FeedbackRequest:
    user = current_user()
    kept = get_session().get(FeedbackRequest, request_id) if in_range(request_id) else None
    if kept is None or kept.sender_id != user.id:
        abort(404)
    return kept


def _show(kept: FeedbackRequest, status: int = 200, headers: dict | None = None, **context):
    """The request as the panel's fragment (asked for by feedback.js, or ``/panel``) or as its own page."""
    values = _request_context(kept, mode="sender", **context)
    values["ask_withdraw"] = request.args.get("withdraw") == "1" and kept.status in service.OPEN
    if _from_panel() or request.endpoint == "feedback.mine_panel":
        return render_template("feedback/_request.html", **values), status, headers or {}
    return (
        render_template(
            "feedback/mine_request.html",
            current_page="mine",
            page_title=f"{values['reference']}: {kept.summary}",
            feedback_script=True,
            **values,
        ),
        status,
        headers or {},
    )


def _after_change(kept: FeedbackRequest, notice: str, tone: str = "success", changed: bool = True):
    """The panel again with ``notice``, or the request's page with ``notice`` as a flash."""
    if _from_panel():
        return _show(kept, notice=notice, notice_tone=tone, headers={"X-Panel-Changed": "1" if changed else "0"})
    flash(notice, tone)
    return redirect(url_for("feedback.mine_request", request_id=kept.id))


def _open(kept: FeedbackRequest):
    """Show the request and mark it seen: opening it, in its panel or on its page, clears the mark."""
    db = get_session()
    had_new_reply = service.has_new_reply(kept)
    service.mark_seen(db, kept)
    db.commit()
    refused = request.args.get("closed") == "1" and kept.status in service.CLOSED
    notice = {"notice": CLOSED_NOTICE, "notice_tone": "warning"} if refused else {}
    return _show(kept, **notice, headers={"X-Panel-Changed": "1" if had_new_reply else "0"})


@bp.get("/feedback/mine")
@login_required
def mine():
    user = current_user()
    db = get_session()
    # The "New reply" mark is worked out for every row in the one query.
    rows = db.execute(
        select(FeedbackRequest, service.unseen_reply())
        .where(FeedbackRequest.sender_id == user.id)
        .order_by(FeedbackRequest.last_activity_at.desc(), FeedbackRequest.id.desc())
    ).all()
    items = [
        {
            "request": kept,
            "reference": service.reference(kept.id),
            "new_reply": bool(new_reply),
            "group": "open" if kept.status in service.OPEN else "closed",
            "activity_key": kept.last_activity_at.astimezone(timezone.utc).isoformat(),
            "sent_key": kept.created_at.astimezone(timezone.utc).isoformat(),
        }
        for kept, new_reply in rows
    ]
    counts = {"all": len(items)}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    return render_template(
        "feedback/mine.html",
        items=items,
        counts=counts,
        filter_options=STATUS_FILTERS,
        status_names=STATUS_NAMES,
        kind_labels=KIND_LABELS,
        when=_when,
        current_page="mine",
        page_title="My feedback",
        feedback_script=True,
    )


@bp.get("/feedback/mine/<int:request_id>")
@login_required
def mine_request(request_id: int):
    return _open(_mine_or_404(request_id))


@bp.get("/feedback/mine/<int:request_id>/panel")
@login_required
def mine_panel(request_id: int):
    return _open(_mine_or_404(request_id))


@bp.post("/feedback/mine/<int:request_id>/message")
@login_required
def mine_message(request_id: int):
    kept = _mine_or_404(request_id)
    if kept.status in service.CLOSED:
        return _refused(kept)
    db = get_session()
    waiting = kept.status == "waiting"
    body = (request.form.get("body") or "").strip()
    form = {"kind": "update", "body": body, "email": True}
    field_errors: dict[str, list[str]] = {}
    if not body:
        field_errors["body"] = [ANSWER_REQUIRED if waiting else MESSAGE_REQUIRED]
    elif len(body) > MAX_REPLY:
        field_errors["body"] = [DETAILS_TOO_LONG]
    files, file_errors = service.check_files(request.files.getlist("files"))
    if file_errors:
        field_errors["files"] = file_errors
    if field_errors:
        return _show(kept, 400, form=form, field_errors=field_errors)
    try:
        message = service.sender_message(db, kept, body, files)
    except ValueError:  # closed since the page was opened
        db.rollback()
        return _refused(kept)
    db.commit()  # the message is kept before any email is tried
    mail.notify_owner(db, kept, message)
    db.commit()
    return _after_change(kept, "Answer sent." if waiting else "Message sent.")


@bp.post("/feedback/mine/<int:request_id>/withdraw")
@login_required
def mine_withdraw(request_id: int):
    kept = _mine_or_404(request_id)
    db = get_session()
    try:
        service.withdraw(db, kept)
    except ValueError:
        db.rollback()
        return _refused(kept)
    db.commit()
    return _after_change(kept, "Request withdrawn.")


def _refused(kept: FeedbackRequest):
    """A closed request is read-only: the form is refused with a message, never an error page."""
    if _from_panel():
        return _show(kept, 409, notice=CLOSED_NOTICE, notice_tone="warning", headers={"X-Panel-Changed": "0"})
    return redirect(url_for("feedback.mine_request", request_id=kept.id, closed=1))
