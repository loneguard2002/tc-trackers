"""Weekly report: model, charts and the live page."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("report", __name__)

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)
