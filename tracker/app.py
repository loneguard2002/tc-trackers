"""Flask application factory for the progress tracker."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

import click
from flask import Flask, jsonify, render_template, request
from jinja2 import StrictUndefined
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .activity import bp as activity_bp
from .admin import bp as admin_bp
from .audit import record
from .auth import bp as auth_bp
from .auth import current_user, has_permission
from .auth.accounts import find_by_email
from .auth.csrf import install_csrf
from .auth.passwords import hash_password, validate_new_password
from .config import load_config, validate_config
from .db import get_session, init_db
from .entries import bp as entries_bp
from .formatting import register_filters
from .importer import bp as importer_bp
from .lists import bp as lists_bp
from .mail import bp as mail_bp
from .models import User
from .permsets import bp as permsets_bp
from .report import bp as report_bp
from .teams import bp as teams_bp
from .trackers import bp as trackers_bp
from .trackers import home

logger = logging.getLogger(__name__)

ERROR_TITLES = {
    400: "Bad request",
    403: "Access denied",
    404: "Page not found",
    405: "Method not allowed",
    413: "Request too large",
}


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(load_config(overrides))
    validate_config(app.config)
    init_db(app)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]

    @app.context_processor
    def common_context():
        return {
            "current_year": datetime.now(timezone.utc).year,
            "app_version": app.config["APP_VERSION"],
            "app_commit": app.config["APP_COMMIT"],
            "app_commit_date": app.config["APP_COMMIT_DATE"],
            "current_user": current_user(),
        }

    @app.context_processor
    def permission_context():
        return {"can": lambda permission: has_permission(current_user(), permission)}

    register_filters(app)
    if app.config.get("TESTING"):
        app.jinja_env.undefined = StrictUndefined
    install_csrf(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(lists_bp)
    app.register_blueprint(permsets_bp)
    app.register_blueprint(activity_bp)
    app.register_blueprint(trackers_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(mail_bp)
    app.register_blueprint(importer_bp)
    if app.config["SSO_ENABLED"]:
        from .auth.sso import bp as sso_bp

        app.register_blueprint(sso_bp)
    _register_cli(app)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; font-src 'self' data:; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, max-age=0"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.add_url_rule("/", endpoint="index", view_func=home)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        status = error.code or 500
        title = ERROR_TITLES.get(status, "Something went wrong")
        return render_template("error.html", status=status, title=title, message=error.description), status

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled error", exc_info=error)
        message = "An unexpected error occurred. Please try again."
        return render_template("error.html", status=500, title="Something went wrong", message=message), 500

    return app


def _read_valid_password(password: str | None) -> str:
    """Prompt (hidden, confirmed) when no password was given, then apply the shared password rules."""
    if password is None:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    problem = validate_new_password(password)
    if problem:
        raise click.ClickException(problem)
    return password


def _register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.argument("email")
    @click.option("--password", default=None, help="Password; prompted for when omitted.")
    @click.option("--name", default=None, help="Full name; defaults to the email address.")
    def create_admin(email: str, password: str | None, name: str | None) -> None:
        """Create an active local administrator."""
        email = email.strip().lower()
        if "@" not in email:
            raise click.ClickException("Enter a valid email address.")
        password = _read_valid_password(password)
        db = get_session()
        if find_by_email(db, email) is not None:
            raise click.ClickException(f"A user with the email {email} already exists.")
        user = User(
            email=email,
            full_name=name or email,
            password_hash=hash_password(password),
            auth_source="local",
            status="active",
            is_admin=True,
        )
        db.add(user)
        db.flush()
        record(
            db,
            user_id=None,
            tracker_id=None,
            action="user_created",
            entity="user",
            entity_id=user.id,
            detail={"email": email, "source": "cli", "is_admin": True},
            target_user_id=user.id,
        )
        db.commit()
        click.echo(f"Created administrator {email}.")

    @app.cli.command("reset-password")
    @click.argument("email")
    @click.option("--password", default=None, help="New password; prompted for (hidden) when omitted.")
    def reset_password(email: str, password: str | None) -> None:
        """Set a new password for an existing local account."""
        email = email.strip().lower()
        password = _read_valid_password(password)
        db = get_session()
        user = find_by_email(db, email)
        if user is None:
            raise click.ClickException(f"No user with the email {email} exists.")
        if user.auth_source != "local":
            raise click.ClickException(f"{email} signs in with single sign-on and has no local password.")
        user.password_hash = hash_password(password)
        record(
            db,
            user_id=None,
            tracker_id=None,
            action="password_reset",
            entity="user",
            entity_id=user.id,
            detail={"email": email, "source": "cli"},
            target_user_id=user.id,
        )
        db.commit()
        click.echo(f"Reset the password for {email}.")

    @app.cli.command("run-scheduler")
    @click.option(
        "--interval", default=60, show_default=True, type=click.IntRange(min=1), help="Seconds between cycles."
    )
    @click.option("--once", is_flag=True, help="Run a single cycle and exit.")
    def run_scheduler(interval: int, once: bool) -> None:
        """Send due weekly reports and retry queued sends, repeatedly."""
        from .sched.runner import run_scheduler_cycle

        while True:
            try:
                with app.app_context():  # a fresh session per cycle, closed on teardown; the SMTP layer shares it
                    count = run_scheduler_cycle(get_session(), datetime.now(timezone.utc))
                logger.info("Scheduler cycle finished: %s send(s) attempted", count)
                click.echo(f"Scheduler cycle finished: {count} send(s) attempted.")
            except Exception:
                logger.exception("Scheduler cycle failed")
                if once:
                    sys.exit(1)
            if once:
                return
            time.sleep(interval)

    @app.cli.command("build-import-template")
    @click.option("--path", default=None, help="Where to write it; defaults to the stored template the page serves.")
    def build_import_template(path: str | None) -> None:
        """Rewrite the import template from the importer's layout (commit the file afterwards)."""
        from .importer.template import TEMPLATE_PATH, write_template

        target = path or TEMPLATE_PATH
        write_template(target)
        click.echo(f"Wrote {target}")

    @app.cli.command("import-workbook")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--name", required=True, help="Name of the new tracker.")
    @click.option(
        "--weekday", default=4, show_default=True, type=click.IntRange(0, 6), help="Week-ending day, Monday=0."
    )
    @click.option("--unit-label", default="", help="The unit being counted.")
    @click.option("--group-label", default="Location", show_default=True, help="The grouping label.")
    @click.option("--owner", default=None, help="Email of the owner; defaults to the only administrator.")
    @click.option("--accept-mismatch", is_flag=True, help="Import even when the reconciliation check differs.")
    def import_workbook(
        path: str, name: str, weekday: int, unit_label: str, group_label: str, owner: str | None, accept_mismatch: bool
    ) -> None:
        """Create a tracker from the existing tracking workbook (a one-time cutover)."""
        from .importer import ImportError_, ImportMismatch, create_tracker_from_preview, read_workbook

        db = get_session()
        if owner:
            user = find_by_email(db, owner.strip().lower())
        else:
            admins = db.query(User).filter(User.is_admin.is_(True), User.status == "active").all()
            user = admins[0] if len(admins) == 1 else None
        if user is None:
            raise click.ClickException("Name the owner with --owner EMAIL (an existing user).")
        try:
            preview = read_workbook(path, weekday)
            click.echo(
                f"Read {len(preview.groups)} group(s), {len(preview.weeks)} week(s), {len(preview.risks)} risk(s). "
                f"Group starting total {preview.group_total}; weekly actuals {preview.weekly_total}; "
                f"difference {preview.mismatch}."
            )
            tracker = create_tracker_from_preview(db, preview, name, unit_label, group_label, user.id, accept_mismatch)
        except ImportMismatch as exc:
            db.rollback()
            raise click.ClickException(f"{exc} Re-run with --accept-mismatch to import regardless.") from exc
        except ImportError_ as exc:
            db.rollback()
            raise click.ClickException(str(exc)) from exc
        db.commit()
        click.echo(f"Imported tracker {tracker.id}.")
