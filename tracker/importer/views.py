"""Upload and confirm pages for the one-time workbook import (holders of the import permission)."""

from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError

from ..auth import current_user, permission_required
from ..db import get_session
from ..lists.catalogue import business_line_choices, parse_business_line, parse_regions, region_choices
from ..teams.tree import TEAM_CHOICE_ERROR, parse_team_id, team_choices
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
            team_choices=team_choices(get_session()),
            business_line_choices=business_line_choices(get_session()),
            region_choices=region_choices(get_session()),
            chosen_regions=set(form.getlist("region_ids")) if hasattr(form, "getlist") else set(),
            page_title="Confirm import",
            current_page="import",
        ),
        status,
    )


@bp.get("/import")
@permission_required("import_workbooks")
def upload():
    return _render_upload()


@bp.post("/import")
@permission_required("import_workbooks")
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
@permission_required("import_workbooks")
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
    team, team_error = parse_team_id(db, form.get("team_id"))
    line, line_error = parse_business_line(db, form.get("business_line_id"), None)
    regions, regions_error = parse_regions(db, form.getlist("region_ids"), ())
    errors = [error for error in (team_error, line_error, regions_error) if error]
    if errors:
        return _render_confirm(parsed, token, form, " ".join(errors), 400)
    try:
        tracker = create_tracker_from_preview(
            db,
            parsed,
            name=form.get("name", ""),
            unit_label=form.get("unit_label", ""),
            group_label=form.get("group_label", ""),
            user_id=current_user().id,
            accept_mismatch=accept,
            team_id=team.id if team else None,
            business_line_id=line.id,
            region_ids=[region.id for region in regions],
        )
        db.commit()
    except IntegrityError:  # the team (or a chosen entry) was deleted at the same moment
        db.rollback()
        return _render_confirm(parsed, token, form, TEAM_CHOICE_ERROR, 400)
    except ImportMismatch as exc:
        db.rollback()
        return _render_confirm(parsed, token, form, f"{exc} Tick the box to import regardless.", 400)
    except ImportError_ as exc:
        db.rollback()
        return _render_confirm(parsed, token, form, str(exc), 400)
    flash("Tracker imported.", "success")
    return redirect(url_for("trackers.settings", tracker_id=tracker.id))
