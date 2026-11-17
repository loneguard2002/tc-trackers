"""Sending the reader back to the view of a list they acted from.

lists.js keeps the view (search, filters, sort, page, rows per page) in the address and posts it with each row action
as a hidden ``view`` field holding ``location.search``. ``list_url`` keeps only the keys the list's own screen
understands and builds the address with ``url_for``: the redirect never takes its target from the request.
"""

from __future__ import annotations

from urllib.parse import parse_qsl

from flask import request, url_for

MAX_VALUE_LENGTH = 200


def kept_view(keys: tuple[str, ...]) -> dict[str, str]:
    """The posted ``view`` reduced to ``keys``: the first value of each, empty or over-long values dropped."""
    kept: dict[str, str] = {}
    view = request.form.get("view", "")[:2000].lstrip("?")
    for name, value in parse_qsl(view, keep_blank_values=False, max_num_fields=50):
        if name in keys and name not in kept and value and len(value) <= MAX_VALUE_LENGTH:
            kept[name] = value
    return kept


def list_url(endpoint: str, keys: tuple[str, ...], **values) -> str:
    """``url_for(endpoint, **values)`` with the posted view's ``keys`` added."""
    return url_for(endpoint, **kept_view(keys), **values)
