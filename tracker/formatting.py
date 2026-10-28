"""Display formatting shared by the live page, the PDF and PNG renderers and the email (Jinja filters)."""

from __future__ import annotations

import base64
from datetime import date

MISSING = "–"


def fmt_pct(value: float | None) -> str:
    """A fraction between 0 and 1 as a whole-number percentage, for example ``37%``."""
    return MISSING if value is None else f"{round(value * 100):d}%"


def fmt_rate(value: float | None) -> str:
    """A rate to one decimal place."""
    return MISSING if value is None else f"{value:.1f}"


def fmt_date(value: date | None) -> str:
    """A date such as ``16 Oct 2026`` (no platform-specific padding directives)."""
    return MISSING if value is None else f"{value.day:02d} {value.strftime('%b %Y')}"


def fmt_num(value: int | float | None) -> str:
    """A whole number with thousands separators, for example ``1,170``."""
    return MISSING if value is None else f"{round(value):,d}"


def fmt_dash(value) -> str:
    """Any value, with ``None`` and empty strings shown as the missing-value dash."""
    return MISSING if value is None or value == "" else str(value)


def fmt_data_uri(data: bytes, mime: str = "image/svg+xml") -> str:
    """Embed image bytes as a ``data:`` URI."""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def fmt_plural(label: str) -> str:
    """A singular label in the plural, for example ``Location`` to ``Locations`` and ``Country`` to ``Countries``."""
    label = label.strip()
    lower = label.lower()
    if not label or lower.endswith("s"):
        return label
    if lower.endswith("y") and lower[-2:-1] not in ("a", "e", "i", "o", "u"):
        return label[:-1] + ("IES" if label.isupper() else "ies")
    if lower.endswith(("x", "z", "ch", "sh")):
        return label + ("ES" if label.isupper() else "es")
    return label + ("S" if label.isupper() else "s")


FILTERS = {
    "pct": fmt_pct,
    "num": fmt_num,
    "rate": fmt_rate,
    "fdate": fmt_date,
    "dash": fmt_dash,
    "data_uri": fmt_data_uri,
    "plural": fmt_plural,
}


def register_filters(app) -> None:
    app.jinja_env.filters.update(FILTERS)
