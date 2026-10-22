"""Data entry: completions, weekly targets, report inputs and risks."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("entries", __name__)

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
