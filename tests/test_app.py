import pytest

from tracker.config import ConfigurationError, load_config, validate_config


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_security_headers(client):
    r = client.get("/healthz")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["X-Frame-Options"] == "DENY"


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
