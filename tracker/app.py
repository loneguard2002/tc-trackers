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

from .admin import bp as admin_bp
from .audit import record
from .auth import bp as auth_bp
from .auth import current_user
from .auth.csrf import install_csrf
from .auth.passwords import hash_password, validate_new_password
from .config import load_config, validate_config
from .db import get_session, init_db
from .entries import bp as entries_bp
from .formatting import register_filters
from .importer import bp as importer_bp
from .mail import bp as mail_bp
from .models import User
from .report import bp as report_bp
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
            "current_user": current_user(),
        }

    register_filters(app)
    if app.config.get("TESTING"):
        app.jinja_env.undefined = StrictUndefined
    install_csrf(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
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
        if password is None:
            password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        problem = validate_new_password(password)
        if problem:
            raise click.ClickException(problem)
        db = get_session()
        if db.query(User).filter(User.email == email).first() is not None:
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
        )
        db.commit()
        click.echo(f"Created administrator {email}.")

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
            user = db.query(User).filter(User.email == owner.strip().lower()).first()
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
