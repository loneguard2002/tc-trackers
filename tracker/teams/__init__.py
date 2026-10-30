"""Teams: the team tree (spec sections 5 and 6.4) and its administration screens (section 7)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("teams", __name__, url_prefix="/admin/teams")

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
