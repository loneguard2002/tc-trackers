import os

import pytest

from tracker.app import create_app

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost/tracker_test")


@pytest.fixture
def app():
    return create_app(
        {"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": DATABASE_URL, "SESSION_COOKIE_SECURE": False}
    )


@pytest.fixture
def client(app):
    return app.test_client()
