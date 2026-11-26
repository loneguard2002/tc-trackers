"""Admin › Sign-in protection: the limits on failed sign-ins, who they block now, and the failures of the last day.

For administrators and holders of the Manage sign-in protection permission. The page names each account (the email
entered) and address (the client's IP) with failures in the last day: the table keeps them for a day, then deletes
them. They can change the limits and unblock an account or address at once; both are written to the activity log.

The same form holds the per-person limit on PDF and PNG report downloads (report/limits.py): another limit that stops
one person from overloading the server, trusted to the same people.

Opening the page marks every block so far as seen for everyone who can open it: the count beside Sign-in protection in
the menu goes back to 0, and the blocks that started since the last visit carry a New badge on this visit only.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for

from ..audit import change, record
from ..auth import current_user, permission_required, throttle
from ..db import get_session
from ..mail.access import mail_configured
from ..report import limits as export_limits
from . import bp

KIND_NAMES = {"account": "Account", "address": "Address"}


def _form(limits: throttle.Limits, per_minute: int) -> dict[str, str]:
    return {**limits.form(), export_limits.FIELD: str(per_minute)}


def _page(limits: throttle.Limits, form: dict | None = None, errors: dict | None = None, status: int = 200):
    db = get_session()
    now, rows = throttle.summaries(db, limits)
    new = throttle.new_blocks(db, throttle.seen_at(db))
    throttle.mark_seen(db, now)
    db.commit()
    blocked = [row for row in rows if row.blocked]
    counts = {
        "all": len(rows),
        "blocked": len(blocked),
        "account": sum(row.kind == "account" for row in rows),
        "address": sum(row.kind == "address" for row in rows),
    }
    return (
        render_template(
            "admin/sign_in.html",
            current_page="sign_in",
            page_title="Sign-in protection",
            limits=limits,
            form=form or _form(limits, export_limits.load_per_minute(db)),
            errors=errors or {},
            fields=throttle.LIMIT_FIELDS,
            download_range=(export_limits.LOWEST, export_limits.HIGHEST),
            now=now,
            rows=rows,
            blocked=blocked,
            counts=counts,
            failures_last_day=sum(row.last_day for row in rows if row.kind == "address"),
            kind_names=KIND_NAMES,
            new=new,
            mail_ready=mail_configured(db),
        ),
        status,
    )


@bp.route("/sign-in-protection", methods=["GET", "POST"])
@permission_required("manage_sign_in_protection")
def sign_in_protection():
    db = get_session()
    before = throttle.load_limits(db)
    if request.method == "GET":
        return _page(before)
    limits, errors = throttle.parse_limits(request.form)
    per_minute, download_error = export_limits.parse_per_minute(request.form.get(export_limits.FIELD))
    if download_error:
        errors[export_limits.FIELD] = download_error
    if errors:
        form = {
            name: request.form.get(name, "") for name in (*throttle.LIMIT_FIELDS, "email_admins", export_limits.FIELD)
        }
        return _page(before, form, errors, 400)
    before_per_minute = export_limits.load_per_minute(db)
    if limits == before and per_minute == before_per_minute:
        flash("The limits are unchanged.", "info")
        return redirect(url_for("admin.sign_in_protection"))
    actor = current_user().id
    if limits != before:
        old, new = before.as_dict(), limits.as_dict()
        changed = [name for name in old if old[name] != new[name]]
        throttle.save_limits(db, limits)
        record(
            db,
            user_id=actor,
            tracker_id=None,
            action="sign_in_limits_changed",
            entity="app_settings",
            entity_id="sign_in_limits",
            detail=change({name: old[name] for name in changed}, {name: new[name] for name in changed}),
        )
    if per_minute != before_per_minute:
        export_limits.save_per_minute(db, per_minute)
        record(
            db,
            user_id=actor,
            tracker_id=None,
            action="download_limit_changed",
            entity="app_settings",
            entity_id=export_limits.SETTING_KEY,
            detail=change({"per_minute": before_per_minute}, {"per_minute": per_minute}),
        )
    db.commit()
    flash("Limits saved. They apply to the next attempt.", "success")
    return redirect(url_for("admin.sign_in_protection"))


@bp.post("/sign-in-protection/unblock")
@permission_required("manage_sign_in_protection")
def sign_in_unblock():
    kind = request.form.get("kind", "")
    value = request.form.get("value", "")
    if kind not in throttle.KINDS or not value or len(value) > throttle.MAX_VALUE_LENGTH:
        abort(400, description="Choose an account or address to unblock.")
    db = get_session()
    removed = throttle.clear(db, kind, value)
    if not removed:
        db.rollback()
        flash(f"{value} has no failed sign-ins to clear.", "info")
        return redirect(url_for("admin.sign_in_protection"))
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="sign_in_unblocked",
        entity="login_failures",
        entity_id=kind,
        detail={KIND_NAMES[kind].lower(): value, "failures_cleared": removed},
    )
    db.commit()
    flash(f"Unblocked {value}: {removed} failed sign-in{'s' if removed != 1 else ''} cleared.", "success")
    return redirect(url_for("admin.sign_in_protection"))
