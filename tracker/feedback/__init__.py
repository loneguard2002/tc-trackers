"""Feedback: ideas and problems from signed-in people, kept as requests with a conversation (see the feedback spec)."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("feedback", __name__)

__all__ = ["bp"]
