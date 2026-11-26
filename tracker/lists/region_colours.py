"""Each region's code shows in one of eight set colours (the owner's choice, 26 Nov 2026), chosen on its Add and Edit
forms. The colours are classes (``region-c1`` to ``region-c8`` in tracker.css), not colours written into the page,
which the Content Security Policy forbids; each is stepped for the light and the dark theme. The colour marks the
code; the code's text keeps the text colour, so it reads the same in every colour."""

from __future__ import annotations

from collections import Counter

from flask import g
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Region

REGION_COLOURS: tuple[str, ...] = ("Blue", "Orange", "Aqua", "Yellow", "Pink", "Green", "Violet", "Red")


def colour_name(colour: int) -> str:
    return REGION_COLOURS[colour - 1] if 1 <= colour <= len(REGION_COLOURS) else str(colour)


def next_colour(db: Session) -> int:
    """The colour a new region starts with: the first one fewest regions use."""
    used = Counter(db.scalars(select(Region.colour)))
    return min(range(1, len(REGION_COLOURS) + 1), key=lambda colour: (used[colour], colour))


def region_colour(code: str | None) -> int | None:
    """The colour of the region with this code (a template global), or ``None`` for no such region; the regions are
    read once a request."""
    if not code:
        return None
    if "region_colours" not in g:
        g.region_colours = {
            c.lower(): colour for c, colour in get_session().execute(select(Region.code, Region.colour))
        }
    return g.region_colours.get(code.lower())
