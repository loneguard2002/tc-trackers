"""Administration: the Users screen (``users``) and the non-secret email settings (``smtp``)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import smtp, users  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
