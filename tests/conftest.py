import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tracker.app import create_app
from tracker.auth.passwords import hash_password
from tracker.models import Base, Tracker, TrackerRole, User

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost/tracker_test")
ROOT = Path(__file__).resolve().parent.parent

_state: dict = {}


@pytest.fixture
def app():
    return create_app(
        {"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": DATABASE_URL, "SESSION_COOKIE_SECURE": False}
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def _db_engine():
    """Probe the database once; migrate once; skip the dependent tests when it is unreachable."""
    if "engine" not in _state:
        engine = create_engine(DATABASE_URL)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            engine.dispose()
            _state["engine"] = None
        else:
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", DATABASE_URL)
            command.upgrade(config, "head")
            _state["engine"] = engine
    if _state["engine"] is None:
        pytest.skip("database unavailable")
    return _state["engine"]


@pytest.fixture
def db(_db_engine):
    session = Session(_db_engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
        with _db_engine.begin() as connection:
            connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def tracker_factory(db):
    def make(**overrides) -> Tracker:
        values = {
            "name": "Test tracker",
            "unit_label": "devices",
            "group_label": "Location",
            "week_ending_weekday": 4,
            "first_week_ending": date(2026, 9, 4),
            "last_week_ending": date(2026, 12, 25),
        }
        values.update(overrides)
        tracker = Tracker(**values)
        db.add(tracker)
        db.commit()
        return tracker

    return make


TEST_PASSWORD = "correct horse battery"


@pytest.fixture
def user_factory(db):
    counter = {"n": 0}

    def make(**overrides) -> User:
        counter["n"] += 1
        values = {
            "email": f"user{counter['n']}@example.com",
            "full_name": f"User {counter['n']}",
            "password_hash": hash_password(TEST_PASSWORD),
            "auth_source": "local",
            "status": "active",
            "is_admin": False,
        }
        values.update(overrides)
        user = User(**values)
        db.add(user)
        db.commit()
        return user

    return make


def sign_in(client, user: User) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
        sess["csrf_token"] = "test-csrf-token"


@pytest.fixture
def logged_in_user(client, user_factory):
    user = user_factory()
    sign_in(client, user)
    return user


@pytest.fixture
def logged_in_admin(client, user_factory):
    user = user_factory(is_admin=True)
    sign_in(client, user)
    return user


@pytest.fixture
def grant(db):
    def give(user: User, tracker: Tracker, role: str) -> None:
        db.add(TrackerRole(user_id=user.id, tracker_id=tracker.id, role=role))
        db.commit()

    return give


def post(client, url: str, data: dict | None = None, **kwargs):
    """POST with the CSRF token of the current session (establishing one when absent)."""
    with client.session_transaction() as sess:
        token = sess.setdefault("csrf_token", "test-csrf-token")
    payload = dict(data or {})
    payload["csrf_token"] = token
    return client.post(url, data=payload, **kwargs)


def _chromium_available() -> bool:
    """Probe once per session whether Playwright's Chromium is installed."""
    if "chromium" not in _state:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                _state["chromium"] = Path(playwright.chromium.executable_path).exists()
        except Exception:
            _state["chromium"] = False
    return _state["chromium"]


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``browser`` when Chromium is not installed."""
    browser_items = [item for item in items if item.get_closest_marker("browser")]
    if browser_items and not _chromium_available():
        skip = pytest.mark.skip(reason="Playwright Chromium is not installed")
        for item in browser_items:
            item.add_marker(skip)
