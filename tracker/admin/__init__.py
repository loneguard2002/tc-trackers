"""Administration: the Users screen (``users``), the non-secret email settings (``smtp``) and the sign-in limits
(``sign_in``)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import sign_in, smtp, users  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
