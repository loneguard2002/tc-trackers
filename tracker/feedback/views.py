"""Feedback pages: sending (the form, a pop-up opened by feedback.js or its own page without JavaScript, and the
thank-you), Admin › Feedback (the table, a request in the side panel or on its own page, replies and statuses) and
the files of a request.

Everyone signed in may send feedback while the Feedback link is on. A request, its conversation and its files are seen
only by its sender and by people who manage feedback; anyone else gets 404 for them, so a guessed id tells nothing.
"""

from __future__ import annotations

import io
from datetime import timezone

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import func, select

from ..auth import current_user, has_permission, login_required, permission_required
from ..auth.csrf import safe_next_url
from ..db import get_session
from ..ids import in_range
from ..mail.access import first_name
from ..models import FeedbackFile, FeedbackMessage, FeedbackRequest, User
from . import bp, mail, service, settings

MAX_SUMMARY = 150
MAX_DETAILS = 5000
MAX_PAGE_TITLE = 200
MAX_PAGE_URL = 500
MAX_BROWSER = 200
# A feedback form carries up to 5 files of 5 MB, so its POST routes take a body of 26 MB (every other route keeps 1 MB).
MAX_BODY = 26 * 1024 * 1024

SUMMARY_ERROR = "Keep it to one line, 150 characters at most."
SUMMARY_REQUIRED = "Say it in one line, 150 characters at most."
DETAILS_REQUIRED = "Say what happened."
DETAILS_TOO_LONG = "Keep this to 5,000 characters at most."
KINDS = ("idea", "problem")


@bp.url_value_preprocessor
def raise_body_limit(endpoint: str | None, values: dict | None) -> None:
    """Take the larger body on this blueprint's POST routes. A plain ``before_request`` of the blueprint is too late:
    the application's CSRF check runs first and reads the form under the 1 MB limit; URL preprocessors run before it."""
    if request.method == "POST":
        request.max_content_length = MAX_BODY


def describe_browser(agent: str) -> str:
    """``Edge on Windows`` from a user agent; empty when it says nothing recognisable."""
    if "Edg/" in agent or "EdgA/" in agent:
        name = "Edge"
    elif "OPR/" in agent:
        name = "Opera"
    elif "Firefox/" in agent:
        name = "Firefox"
    elif "Chrome/" in agent or "CriOS/" in agent:
        name = "Chrome"
    elif "Safari/" in agent:
        name = "Safari"
    else:
        return ""
    for marker, system in (
        ("Windows", "Windows"),
        ("Android", "Android"),
        ("iPhone", "iOS"),
        ("iPad", "iOS"),
        ("Mac OS X", "macOS"),
        ("Linux", "Linux"),
    ):
        if marker in agent:
            return f"{name} on {system}"
    return name


def _back(value: str | None) -> str:
    """The page the person was on (a path of this site), or the home page."""
    return (safe_next_url(value) or "/")[:MAX_PAGE_URL]


def _render_form(status: int, form: dict, errors: list[str], field_errors: dict[str, list[str]]):
    user = current_user()
    return (
        render_template(
            "feedback/send.html",
            form=form,
            errors=errors,
            field_errors=field_errors,
            sender=user,
            page_title="Send feedback",
        ),
        status,
    )


def _form_from_query() -> dict:
    agent = describe_browser(request.headers.get("User-Agent", ""))
    page = safe_next_url(request.args.get("page")) or ""
    return {
        "kind": "idea",
        "summary": "",
        "details": "",
        "with_page": True,
        "page_title": (request.args.get("title") or "").strip()[:MAX_PAGE_TITLE],
        "page_url": page[:MAX_PAGE_URL],
        "back": _back(page),
        "browser": agent,
    }


@bp.route("/feedback/new", methods=["GET", "POST"])
@login_required
def send():
    db = get_session()
    if not settings.link_on(db):
        abort(404)
    if request.method == "GET":
        return _render_form(200, _form_from_query(), [], {})
    user = current_user()
    kind = request.form.get("kind", "idea")
    kind = kind if kind in KINDS else "idea"
    summary = " ".join((request.form.get("summary") or "").split())
    details = (request.form.get("details") or "").strip()
    with_page = bool(request.form.get("with_page"))
    form = {
        "kind": kind,
        "summary": summary,
        "details": details,
        "with_page": with_page,
        "page_title": " ".join((request.form.get("page_title") or "").split())[:MAX_PAGE_TITLE],
        "page_url": (safe_next_url(request.form.get("page_url")) or "")[:MAX_PAGE_URL],
        "back": _back(request.form.get("back")),
        "browser": " ".join((request.form.get("browser") or "").split())[:MAX_BROWSER]
        or describe_browser(request.headers.get("User-Agent", "")),
    }
    field_errors: dict[str, list[str]] = {}
    if not summary:
        field_errors["summary"] = [SUMMARY_REQUIRED]
    elif len(summary) > MAX_SUMMARY:
        field_errors["summary"] = [SUMMARY_ERROR]
    if kind == "problem" and not details:
        field_errors["details"] = [DETAILS_REQUIRED]
    elif len(details) > MAX_DETAILS:
        field_errors["details"] = [DETAILS_TOO_LONG]
    files, file_errors = service.check_files(request.files.getlist("files"))
    if file_errors:
        field_errors["files"] = file_errors
    if field_errors:
        return _render_form(400, form, [], field_errors)

    kept = form if with_page else {"page_title": "", "page_url": "", "browser": ""}
    created = service.create_request(
        db, user, kind, summary, details, kept["page_title"], kept["page_url"], kept["browser"], files
    )
    db.commit()  # the request is kept before any email is tried
    first = db.scalar(
        select(FeedbackMessage).where(FeedbackMessage.request_id == created.id).order_by(FeedbackMessage.id).limit(1)
    )
    mail.notify_owner(db, created, first)
    db.commit()
    return redirect(url_for("feedback.sent", request_id=created.id, back=form["back"]))


@bp.get("/feedback/sent/<int:request_id>")
@login_required
def sent(request_id: int):
    user = current_user()
    kept = get_session().get(FeedbackRequest, request_id) if in_range(request_id) else None
    if kept is None or kept.sender_id != user.id:
        abort(404)
    return render_template(
        "feedback/sent.html",
        kept=kept,
        reference=service.reference(kept.id),
        name=first_name(user),
        back=_back(request.args.get("back")),
        page_title="Thank you",
    )


# ---- Admin › Feedback: the table, a request in the side panel or on its own page, replies and statuses -------------

MAX_REPLY = 5000
REPLY_KINDS = ("update", "question")
REPLY_REQUIRED = {"update": "Write your update.", "question": "Write your question."}
STATUS_UNKNOWN = "Choose a status from the list."
PICTURE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
KIND_LABELS = {"idea": "Idea", "problem": "Problem"}
STATUS_NAMES = dict(zip(service.STATUSES, service.STATUS_LABELS))
# The status buttons over the table; the first is the view the page opens on.
STATUS_FILTERS = (
    ("open", "Open"),
    ("new", "New"),
    ("waiting", "Waiting for an answer"),
    ("planned", "Planned"),
    ("closed", "Closed"),
    ("all", "All"),
)
TIME_FORMAT = "%d %b %Y at %H:%M UTC"
SHORT_TIME_FORMAT = "%d %b %Y, %H:%M"


def _reviewer_or_404():
    """The signed-in person when they manage feedback. Anyone else gets 404, so a guessed id tells them nothing."""
    user = current_user()
    if not has_permission(user, "manage_feedback"):
        abort(404)
    return user


def _request_or_404(request_id: int) -> FeedbackRequest:
    kept = get_session().get(FeedbackRequest, request_id) if in_range(request_id) else None
    if kept is None:
        abort(404)
    return kept


def _from_panel() -> bool:
    """A form posted from the side panel (feedback.js) gets the panel back instead of a redirect."""
    return request.headers.get("X-Requested-With") == "fetch"


def _when(moment, short: bool = False) -> str:
    """``25 Nov 2026 at 10:42 UTC``, or ``25 Nov 2026, 10:42`` for the table (whose page says the times are UTC)."""
    return moment.astimezone(timezone.utc).strftime(SHORT_TIME_FORMAT if short else TIME_FORMAT) if moment else ""


def _can_email(person: User | None) -> bool:
    return person is not None and person.status == "active"


@bp.get("/admin/feedback")
@permission_required("manage_feedback")
def admin_index():
    db = get_session()
    # The Replies column counts the reviewers' updates and questions, worked out for every row in the one query.
    reply_counts = (
        select(FeedbackMessage.request_id, func.count().label("n"))
        .where(FeedbackMessage.kind.in_(REPLY_KINDS))
        .group_by(FeedbackMessage.request_id)
        .subquery()
    )
    rows = db.execute(
        select(FeedbackRequest, User.full_name, func.coalesce(reply_counts.c.n, 0))
        .outerjoin(User, User.id == FeedbackRequest.sender_id)
        .outerjoin(reply_counts, reply_counts.c.request_id == FeedbackRequest.id)
        .order_by(FeedbackRequest.last_activity_at.desc(), FeedbackRequest.id.desc())
    ).all()
    items = [
        {
            "request": kept,
            "reference": service.reference(kept.id),
            "sender": sender_name or "",
            "replies": count,
            "group": "open" if kept.status in service.OPEN else "closed",
            "activity_key": kept.last_activity_at.astimezone(timezone.utc).isoformat(),
        }
        for kept, sender_name, count in rows
    ]
    counts = {"all": len(items)}
    for item in items:
        for token in (item["group"], item["request"].status):
            counts[token] = counts.get(token, 0) + 1
    return render_template(
        "feedback/admin_index.html",
        items=items,
        counts=counts,
        filter_options=STATUS_FILTERS,
        status_names=STATUS_NAMES,
        kind_labels=KIND_LABELS,
        chosen_kind=request.args.get("region", ""),
        when=_when,
        current_page="feedback",
        page_title="Feedback",
        feedback_script=True,
    )


def _request_context(
    kept: FeedbackRequest, form: dict | None = None, field_errors=None, notice: str = "", notice_tone: str = "success"
) -> dict:
    """What ``feedback/_request.html`` shows: the head, the conversation oldest first with its files, and the forms."""
    db = get_session()
    messages = list(
        db.scalars(select(FeedbackMessage).where(FeedbackMessage.request_id == kept.id).order_by(FeedbackMessage.id))
    )
    files: dict[int, list] = {}
    for row in db.execute(
        select(FeedbackFile.id, FeedbackFile.message_id, FeedbackFile.filename, FeedbackFile.content_type)
        .where(FeedbackFile.request_id == kept.id)
        .order_by(FeedbackFile.id)
    ):
        files.setdefault(row.message_id, []).append(
            {"id": row.id, "name": row.filename, "picture": row.content_type in PICTURE_TYPES}
        )
    people_ids = {m.author_id for m in messages if m.author_id} | ({kept.sender_id} if kept.sender_id else set())
    people = {person.id: person for person in db.scalars(select(User).where(User.id.in_(people_ids)))}
    sender = people.get(kept.sender_id)
    return {
        "kept": kept,
        "reference": service.reference(kept.id),
        "kind_name": KIND_LABELS[kept.kind],
        "sender_name": (sender.full_name if sender else "") or "the sender",
        "can_email": _can_email(sender),
        "messages": messages,
        "files": files,
        "people": people,
        "statuses": list(zip(service.STATUSES, service.STATUS_LABELS)),
        "status_names": STATUS_NAMES,
        "when": _when,
        "form": form or {"kind": "update", "body": "", "email": True},
        "field_errors": field_errors or {},
        "notice": notice,
        "notice_tone": notice_tone,
        "mode": "reviewer",
    }


def _show_request(kept: FeedbackRequest, status: int = 200, **context):
    """The request as the side panel's fragment (asked for by feedback.js) or as its own page."""
    values = _request_context(kept, **context)
    if _from_panel() or request.endpoint == "feedback.admin_panel":
        return render_template("feedback/_request.html", **values), status
    return (
        render_template(
            "feedback/admin_request.html",
            current_page="feedback",
            page_title=f"{values['reference']}: {kept.summary}",
            feedback_script=True,
            **values,
        ),
        status,
    )


def _after_change(kept: FeedbackRequest, notice: str, warning: bool = False):
    tone = "warning" if warning else "success"
    if _from_panel():
        return _show_request(kept, notice=notice, notice_tone=tone)
    flash(notice, tone)
    return redirect(url_for("feedback.admin_request", request_id=kept.id))


@bp.get("/admin/feedback/<int:request_id>")
@login_required
def admin_request(request_id: int):
    _reviewer_or_404()
    return _show_request(_request_or_404(request_id))


@bp.get("/admin/feedback/<int:request_id>/panel")
@login_required
def admin_panel(request_id: int):
    _reviewer_or_404()
    return _show_request(_request_or_404(request_id))


@bp.post("/admin/feedback/<int:request_id>/status")
@login_required
def admin_status(request_id: int):
    user = _reviewer_or_404()
    kept = _request_or_404(request_id)
    db = get_session()
    status = request.form.get("status", "")
    try:
        service.set_status(db, kept, user, status)
    except ValueError:
        db.rollback()
        return _show_request(kept, 400, field_errors={"status": [STATUS_UNKNOWN]})
    db.commit()
    return _after_change(kept, f"Status saved: {STATUS_NAMES[kept.status]}.")


@bp.post("/admin/feedback/<int:request_id>/reply")
@login_required
def admin_reply(request_id: int):
    user = _reviewer_or_404()
    kept = _request_or_404(request_id)
    db = get_session()
    kind = request.form.get("kind", "update")
    kind = kind if kind in REPLY_KINDS else "update"
    body = (request.form.get("body") or "").strip()
    form = {"kind": kind, "body": body, "email": bool(request.form.get("email"))}
    field_errors: dict[str, list[str]] = {}
    if not body:
        field_errors["body"] = [REPLY_REQUIRED[kind]]
    elif len(body) > MAX_REPLY:
        field_errors["body"] = [DETAILS_TOO_LONG]
    files, file_errors = service.check_files(request.files.getlist("files"))
    if file_errors:
        field_errors["files"] = file_errors
    if field_errors:
        return _show_request(kept, 400, form=form, field_errors=field_errors)
    try:
        message = service.reviewer_reply(db, kept, user, kind, body, files)
    except ValueError:
        db.rollback()
        abort(400)
    db.commit()  # the reply is kept before any email is tried
    note = ""
    sender = db.get(User, kept.sender_id) if kept.sender_id else None
    if form["email"] and _can_email(sender):
        note = mail.notify_sender(db, kept, message)
        db.commit()
    done = "Question sent." if kind == "question" else "Update sent."
    return _after_change(kept, f"{done} {note}." if note else done, warning=bool(note))


@bp.get("/feedback/files/<int:file_id>")
@login_required
def file(file_id: int):
    """A file of a request, for its sender and for people who manage feedback; 404 for anyone else. Pictures show in
    the page; every other file is a download, and nothing is sniffed into another type."""
    user = current_user()
    db = get_session()
    found = (
        db.execute(
            select(FeedbackFile, FeedbackRequest.sender_id)
            .join(FeedbackRequest, FeedbackRequest.id == FeedbackFile.request_id)
            .where(FeedbackFile.id == file_id)
        ).first()
        if in_range(file_id)
        else None
    )
    if found is None or not (found.sender_id == user.id or has_permission(user, "manage_feedback")):
        abort(404)
    kept = found[0]
    picture = kept.content_type in PICTURE_TYPES
    response = send_file(
        io.BytesIO(kept.data),
        mimetype=kept.content_type,
        as_attachment=not picture,
        download_name=kept.filename or "file",
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
