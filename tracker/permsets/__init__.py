"""Permission sets: the permissions grid and who holds each set (spec sections 6.2 and 7). Administrators only."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("permsets", __name__, url_prefix="/admin/permission-sets")

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
