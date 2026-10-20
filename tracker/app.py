"""Flask application factory for the progress tracker."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import load_config, validate_config
from .db import init_db

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
            "is_admin": bool(session.get("is_admin")),
        }

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
