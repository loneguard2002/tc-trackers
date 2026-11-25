import pytest

from tracker.config import ConfigurationError, load_config, validate_config


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_security_headers(client):
    r = client.get("/healthz")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert "img-src 'self' data:" in csp
    assert r.headers["X-Frame-Options"] == "DENY"


def test_pages_are_never_stored_but_static_files_may_be(client):
    """Every page and file the app builds is sent "never store", so no browser shows stale figures; the
    stylesheets and scripts under /static are left to the normal static-file caching."""
    assert client.get("/healthz").headers["Cache-Control"] == "no-store, max-age=0"
    assert "no-store" not in client.get("/static/tracker.css").headers.get("Cache-Control", "")


def test_missing_database_url_fails_fast():
    with pytest.raises(ConfigurationError):
        validate_config({"SECRET_KEY": "x", "DATABASE_URL": ""})


def test_sso_disabled_without_all_three_settings():
    cfg = load_config({"SECRET_KEY": "x", "DATABASE_URL": "postgresql+psycopg://u@h/d", "SSO_TENANT_ID": "t"})
    assert cfg["SSO_ENABLED"] is False


def test_sso_enabled_with_all_three_settings():
    cfg = load_config({"SSO_TENANT_ID": "t", "SSO_CLIENT_ID": "c", "SSO_CLIENT_SECRET": "s"})
    assert cfg["SSO_ENABLED"] is True


def test_short_secret_rejected_outside_testing():
    with pytest.raises(ConfigurationError):
        validate_config({"SECRET_KEY": "short", "DATABASE_URL": "postgresql+psycopg://u@h/d"})


def test_not_found_renders_error_page(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert b"Page not found" in r.data
    assert b"Trackers" in r.data


def test_a_database_error_still_shows_the_styled_error_page(app, client, user_factory):
    from conftest import sign_in
    from sqlalchemy import text

    from tracker.auth import current_user, has_permission, login_required
    from tracker.db import get_session

    @login_required
    def boom():
        has_permission(current_user(), "view_activity")
        get_session().execute(text("select 1/0"))
        return "never"

    app.add_url_rule("/test-database-error", "test_database_error", boom)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    sign_in(client, user_factory(full_name="Pat Probe", email="pat@example.com"))
    response = client.get("/test-database-error")
    assert response.status_code == 500
    assert "Something went wrong" in response.get_data(as_text=True)
