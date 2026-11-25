"""Sending feedback: the form (a pop-up opened by feedback.js, or its own page without JavaScript) and the thank-you.

Everyone signed in may send feedback while the Feedback link is on. A request is seen only by its sender and by people
who manage feedback, so the thank-you page answers 404 to anyone else.
"""

from __future__ import annotations

from flask import abort, redirect, render_template, request, url_for
from sqlalchemy import select

from ..auth import current_user, login_required
from ..auth.csrf import safe_next_url
from ..db import get_session
from ..ids import in_range
from ..mail.access import first_name
from ..models import FeedbackMessage, FeedbackRequest
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
