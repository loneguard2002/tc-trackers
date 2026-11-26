"""The shared pieces of the tables that page, sort and search on the server (Activity and Entries).

The address carries ``q``, ``sort`` (a column key, ``-`` before it for descending), ``page`` and ``size``; a value that
is the default is left out. The footer and headings in ``lists/_table.html`` (``server_pager``, ``server_sort_header``)
look like the browser-side tables' and take what is built here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

PAGE_SIZES = (25, 50, 100)
DEFAULT_SIZE = PAGE_SIZES[0]
MAX_QUERY_LENGTH = 200


@dataclass(frozen=True)
class TableState:
    q: str
    sort: str
    descending: bool
    page: int
    size: int


def read_state(args, sort_keys: tuple[str, ...], default_sort: str, default_descending: bool) -> TableState:
    """The table's state from the request's query string; anything unusable falls back to the default."""
    q = (args.get("q") or "").strip()[:MAX_QUERY_LENGTH]
    raw = (args.get("sort") or "").strip()
    descending = raw.startswith("-")
    key = raw[1:] if descending else raw
    if key not in sort_keys:
        key, descending = default_sort, default_descending
    try:
        size = int(args.get("size", ""))
    except (TypeError, ValueError):
        size = DEFAULT_SIZE
    if size not in PAGE_SIZES:
        size = DEFAULT_SIZE
    try:
        page = int(args.get("page", ""))
    except (TypeError, ValueError):
        page = 1
    return TableState(q=q, sort=key, descending=descending, page=max(1, page), size=size)


def like_pattern(text: str) -> str:
    """The text as a contains-pattern for ``ILIKE ... ESCAPE '\\'``, with ``\\``, ``%`` and ``_`` matching literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def page_count(total: int, size: int) -> int:
    return max(1, -(-total // size))


def clamp_page(state: TableState, total: int) -> TableState:
    """The state with its page brought within 1..last (a page past the end shows the last page)."""
    page = min(state.page, page_count(total, state.size))
    return state if page == state.page else dataclasses.replace(state, page=page)


def page_numbers(page: int, last: int) -> list[int | None]:
    """The page numbers to show, as lists.js does: the first and last always, those beside the current page, and
    ``None`` where numbers are left out."""
    numbers: list[int | None] = []
    previous = 0
    for number in range(1, last + 1):
        if number not in (1, last) and abs(number - page) > 1:
            continue
        if previous and number - previous > 1:
            numbers.append(None)
        numbers.append(number)
        previous = number
    return numbers


def state_args(state: TableState, default_sort: str, default_descending: bool, **changes) -> dict:
    """The address arguments for ``state`` with ``changes`` applied (any of q, sort, descending, page, size); the
    defaults are left out. For ``url_for(endpoint, **other_keys, **state_args(...))``."""
    state = dataclasses.replace(state, **changes)
    args: dict = {}
    if state.q:
        args["q"] = state.q
    if (state.sort, state.descending) != (default_sort, default_descending):
        args["sort"] = ("-" if state.descending else "") + state.sort
    if state.page > 1:
        args["page"] = state.page
    if state.size != DEFAULT_SIZE:
        args["size"] = state.size
    return args


def sort_changes(state: TableState, key: str) -> dict:
    """The ``state_args`` changes for a click on column ``key``: the sorted column reverses, another starts
    ascending; either way the table returns to page 1."""
    return {"sort": key, "descending": (not state.descending) if state.sort == key else False, "page": 1}
