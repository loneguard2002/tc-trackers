"""Database-free tests for authentication helpers."""

import pytest
from flask import Flask

from tracker.auth.csrf import LoginThrottle, csrf_token, safe_next_url, valid_csrf
from tracker.auth.passwords import MIN_PASSWORD_LENGTH, hash_password, validate_new_password, verify_password
from tracker.config import load_config


def test_hash_and_verify_password():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_never_raises_on_bad_input():
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "") is False


def test_validate_new_password_rules():
    assert validate_new_password("a" * (MIN_PASSWORD_LENGTH - 1)) is not None
    assert validate_new_password("a" * 73) is not None
    assert validate_new_password("a" * MIN_PASSWORD_LENGTH) is None


def test_login_throttle_blocks_after_attempts_and_clears():
    throttle = LoginThrottle(attempts=5, window_seconds=300)
    for _ in range(4):
        throttle.fail("k")
    assert not throttle.blocked("k")
    throttle.fail("k")
    assert throttle.blocked("k")
    assert not throttle.blocked("other")
    throttle.clear("k")
    assert not throttle.blocked("k")


def _flask():
    app = Flask(__name__)
    app.secret_key = "x"
    return app


def test_csrf_token_is_stable_and_validated():
    with _flask().test_request_context():
        token = csrf_token()
        assert csrf_token() == token
        assert valid_csrf(token)
        assert not valid_csrf("nope")
        assert not valid_csrf(None)
        assert not valid_csrf("")


def test_valid_csrf_false_without_session_token():
    with _flask().test_request_context():
        assert not valid_csrf("anything")


@pytest.mark.parametrize("value", [None, "", "https://evil.example/", "//evil.example", "/\\evil.example", "evil"])
def test_safe_next_url_rejects_unsafe(value):
    assert safe_next_url(value) is None


def test_safe_next_url_accepts_local_path():
    assert safe_next_url("/trackers/1?x=2") == "/trackers/1?x=2"


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "Off"])
def test_session_cookie_secure_false_only_for_explicit_values(monkeypatch, raw):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", raw)
    assert load_config()["SESSION_COOKIE_SECURE"] is False


@pytest.mark.parametrize("raw", ["true", "1", "yes", "flase", "", "garbage"])
def test_session_cookie_secure_fails_closed(monkeypatch, raw):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", raw)
    assert load_config()["SESSION_COOKIE_SECURE"] is True


def test_session_cookie_secure_defaults_true(monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    assert load_config()["SESSION_COOKIE_SECURE"] is True


def _app_without_sso():
    from tracker.app import create_app

    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE_URL": "postgresql+psycopg://localhost/unused",
            "SSO_TENANT_ID": "",
            "SSO_CLIENT_ID": "",
            "SSO_CLIENT_SECRET": "",
        }
    )


def test_sso_routes_absent_when_disabled():
    client = _app_without_sso().test_client()
    assert client.get("/auth/sso").status_code == 404
    assert client.get("/auth/callback").status_code == 404


def test_post_without_csrf_rejected_before_any_view():
    client = _app_without_sso().test_client()
    assert client.post("/login", data={"email": "a@example.com", "password": "x"}).status_code == 400
    assert client.post("/logout").status_code == 400


def test_login_page_renders_without_session_user():
    client = _app_without_sso().test_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert b"csrf_token" in response.data
    assert b"Sign in with Microsoft" not in response.data


def test_admin_pages_redirect_anonymous_to_login():
    client = _app_without_sso().test_client()
    response = client.get("/admin/users")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_tracker_pages_redirect_anonymous_to_login():
    client = _app_without_sso().test_client()
    response = client.get("/trackers/1")
    assert response.status_code == 302 and "/login" in response.headers["Location"]
