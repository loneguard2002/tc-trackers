"""Admin › Sign-in protection: the limits on failed sign-ins, who they block now, and the failures of the last day.

For administrators and holders of the Manage sign-in protection permission. The page names each account (the email
entered) and address (the client's IP) with failures in the last day: the table keeps them for a day, then deletes
them. They can change the limits and unblock an account or address at once; both are written to the activity log.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for

from ..audit import change, record
from ..auth import current_user, permission_required, throttle
from ..db import get_session
from . import bp

KIND_NAMES = {"account": "Account", "address": "Address"}


def _page(limits: throttle.Limits, form: dict | None = None, errors: dict | None = None, status: int = 200):
    db = get_session()
    now, rows = throttle.summaries(db, limits)
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
            form=form or {name: str(value) for name, value in limits.as_dict().items()},
            errors=errors or {},
            fields=throttle.LIMIT_FIELDS,
            now=now,
            rows=rows,
            blocked=blocked,
            counts=counts,
            failures_last_day=sum(row.last_day for row in rows if row.kind == "address"),
            kind_names=KIND_NAMES,
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
    if limits is None:
        form = {name: request.form.get(name, "") for name in throttle.LIMIT_FIELDS}
        return _page(before, form, errors, 400)
    if limits == before:
        flash("The limits are unchanged.", "info")
        return redirect(url_for("admin.sign_in_protection"))
    old, new = before.as_dict(), limits.as_dict()
    changed = [name for name in throttle.LIMIT_FIELDS if old[name] != new[name]]
    throttle.save_limits(db, limits)
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="sign_in_limits_changed",
        entity="app_settings",
        entity_id="sign_in_limits",
        detail=change({name: old[name] for name in changed}, {name: new[name] for name in changed}),
    )
    db.commit()
    flash("Sign-in limits saved. They apply to the next attempt.", "success")
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
