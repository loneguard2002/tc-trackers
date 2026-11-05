"""Administered lists: regions, locations and business lines. Administrators only."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("lists", __name__, url_prefix="/admin")

from . import access, views  # noqa: E402,F401  (registers the routes on ``bp``)

__all__ = ["bp"]
