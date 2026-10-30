"""Record ids typed into forms, query strings and URLs.

Every id column is a Postgres ``integer``, so an id above ``MAX_ID`` cannot exist and must not reach a query (it would
fail there with a 500). The length is checked before ``int()``, which refuses strings of more than 4,300 digits.
"""

from __future__ import annotations

MAX_ID = 2**31 - 1  # the largest Postgres integer
_MAX_DIGITS = len(str(MAX_ID))


def parse_id(value: str | None) -> int | None:
    """A positive id from text (surrounding spaces allowed), or ``None`` for anything else."""
    text = (value or "").strip()
    if not text or len(text) > _MAX_DIGITS or not (text.isascii() and text.isdigit()):
        return None
    number = int(text)
    return number if 0 < number <= MAX_ID else None


def in_range(number: int) -> bool:
    """Whether an id taken from a URL (Flask's ``int`` converter has no upper bound) can exist."""
    return 0 < number <= MAX_ID
