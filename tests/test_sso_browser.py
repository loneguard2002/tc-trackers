"""Microsoft sign-in with response_mode=form_post, in a real browser (database).

A fake identity provider on ``localhost`` posts the result to the app on ``127.0.0.1``: two different sites, so the
post is cross-site as Microsoft's is, and the browser applies its real SameSite rules to both cookies.
"""

from __future__ import annotations

import threading

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_sso import claims
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

from tracker.auth import sso
from tracker.models import User

pytestmark = pytest.mark.browser


def _serve(app, host: str):
    server = make_server(host, 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FakeMicrosoft:
    """Sends the browser to the fake provider, then checks the posted state against the flow, as MSAL does."""

    def __init__(self, provider_url: str):
        self.provider_url = provider_url

    def initiate_auth_code_flow(self, scopes, redirect_uri, response_mode=None):
        assert response_mode == "form_post"
        return {"auth_uri": self.provider_url, "state": "s", "nonce": "n"}

    def acquire_token_by_auth_code_flow(self, flow, auth_response):
        if auth_response.get("state") != flow["state"]:
            raise ValueError("state mismatch")
        return claims(name="Sam Taylor", email="sam@example.com")


def test_the_flow_cookie_survives_microsofts_cross_site_post(page, sso_app, db, monkeypatch):
    app_server = _serve(sso_app, "127.0.0.1")
    callback = f"http://127.0.0.1:{app_server.server_port}/auth/callback"

    @Request.application
    def provider(request):
        fields = '<input name="code" value="c"><input name="state" value="s">'
        form = f'<form method="post" action="{callback}">{fields}</form>'
        return Response(form + "<script>document.forms[0].submit()</script>", mimetype="text/html")

    provider_server = _serve(provider, "localhost")
    monkeypatch.setattr(sso, "_msal_app", lambda: FakeMicrosoft(f"http://localhost:{provider_server.server_port}/"))
    try:
        page.goto(f"http://127.0.0.1:{app_server.server_port}/auth/sso")
        expect(page.get_by_role("heading", name="Thanks, Sam. Your access request has been sent.")).to_be_visible()
        assert page.url.endswith("/auth/pending")
        assert db.scalar(select(User).where(User.email == "sam@example.com")).status == "pending"
        assert not [c for c in page.context.cookies() if c["name"] == sso.FLOW_COOKIE]  # used once, then removed
    finally:
        app_server.shutdown()
        provider_server.shutdown()
