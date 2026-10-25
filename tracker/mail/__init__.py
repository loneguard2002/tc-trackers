"""Report email: recipients, template, composition, sending and the retry queue (spec section 8)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("mail", __name__)

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)
