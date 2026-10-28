"""Upload and confirm pages for the one-time workbook import (administrators only)."""

from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..auth import admin_required, current_user
from ..db import get_session
from ..trackers.views import WEEKDAYS
from . import bp
from .workbook import ImportError_, ImportMismatch, ImportPreview, create_tracker_from_preview, read_workbook

SALT = "workbook-import"
MAX_AGE_SECONDS = 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=SALT)


def _render_upload(error: str | None = None, weekday: int = 4, status: int = 200):
    return (
        render_template(
            "importer/upload.html",
            error=error,
            weekday=weekday,
            weekdays=list(enumerate(WEEKDAYS)),
            page_title="Import workbook",
            current_page="import",
        ),
        status,
    )


def _render_confirm(preview: ImportPreview, token: str, form, error: str | None = None, status: int = 200):
    return (
        render_template(
            "importer/confirm.html",
            preview=preview,
            token=token,
            form=form,
            error=error,
            weekdays=WEEKDAYS,
            page_title="Confirm import",
            current_page="import",
        ),
        status,
    )


@bp.get("/import")
@admin_required
def upload():
    return _render_upload()


@bp.post("/import")
@admin_required
def preview():
    try:
        weekday = int(request.form.get("weekday", "4"))
    except ValueError:
        return _render_upload("Choose a week-ending day.", status=400)
    upload_file = request.files.get("workbook")
    if upload_file is None or not upload_file.filename:
        return _render_upload("Choose a workbook file to upload.", weekday, 400)
    try:
        parsed = read_workbook(upload_file.stream, weekday)
    except ImportError_ as exc:
        return _render_upload(str(exc), weekday, 400)
    token = _serializer().dumps(parsed.to_json())
    return _render_confirm(parsed, token, {"group_label": "Location"})


@bp.post("/import/confirm")
@admin_required
def confirm():
    token = request.form.get("payload", "")
    try:
        parsed = ImportPreview.from_json(_serializer().loads(token, max_age=MAX_AGE_SECONDS))
    except (BadSignature, ImportError_):  # SignatureExpired is a BadSignature
        flash("The import preview has expired or is not valid. Upload the workbook again.", "danger")
        return redirect(url_for("importer.upload"))
    form = request.form
    accept = form.get("accept_mismatch") == "1"
    db = get_session()
    try:
        tracker = create_tracker_from_preview(
            db,
            parsed,
            name=form.get("name", ""),
            unit_label=form.get("unit_label", ""),
            group_label=form.get("group_label", ""),
            user_id=current_user().id,
            accept_mismatch=accept,
        )
    except ImportMismatch as exc:
        db.rollback()
        return _render_confirm(parsed, token, form, f"{exc} Tick the box to import regardless.", 400)
    except ImportError_ as exc:
        db.rollback()
        return _render_confirm(parsed, token, form, str(exc), 400)
    db.commit()
    flash("Tracker imported.", "success")
    return redirect(url_for("trackers.settings", tracker_id=tracker.id))
