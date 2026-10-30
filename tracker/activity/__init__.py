"""Activity screen: who did what, to whom and when (spec sections 2, 7 and 8.1). Holders of ``view_activity`` only."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("activity", __name__, url_prefix="/admin/activity")

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
