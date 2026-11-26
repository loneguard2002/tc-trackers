"""The Teams pages' two views (the owner's choice, 26 Nov 2026): New (the access map) and Classic (the pages as they
were). The choice is kept in the session, as the report's is; New is the default (``TEAMS_DEFAULT_VIEW``)."""

from __future__ import annotations

from flask import current_app, request, session, url_for

VIEWS = ("new", "classic")
VIEW_KEY = "teams_view"


def chosen_view() -> str:
    """The view asked for with ``?view=`` (kept for the next page), else the one kept, else the default. The session
    is written only when the choice changes."""
    asked = request.args.get("view")
    kept = session.get(VIEW_KEY)
    default = current_app.config.get("TEAMS_DEFAULT_VIEW", "new")
    chosen = asked if asked in VIEWS else kept if kept in VIEWS else default
    if kept != chosen:
        session[VIEW_KEY] = chosen
    return chosen


def switch_urls(endpoint: str, **values) -> dict[str, str]:
    """The current page's address in each view: on a GET, its own address and query with ``view`` set; after a
    form was sent (a refusal shown again), ``endpoint`` with ``values``, the page the form belongs to."""
    if request.method == "GET" and request.endpoint:
        endpoint = request.endpoint
        values = {key: value for key, value in request.args.items() if key != "view"}
        values.update(request.view_args or {})
    return {view: url_for(endpoint, **values, view=view) for view in VIEWS}
