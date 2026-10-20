import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tracker.app import create_app
from tracker.models import Base, Tracker

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
