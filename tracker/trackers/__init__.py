"""Trackers: home page, settings, groups and role assignment."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("trackers", __name__)

from . import views  # noqa: E402,F401  (registers the routes on ``bp``)
from .views import home, load_engine_inputs, tracker_summary  # noqa: E402

__all__ = ["bp", "home", "load_engine_inputs", "tracker_summary"]
