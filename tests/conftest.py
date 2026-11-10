import functools
import itertools
import os
import string
import threading
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from tracker.app import create_app
from tracker.auth.passwords import hash_password
from tracker.db import get_engine
from tracker.models import (
    Base,
    BusinessLine,
    Location,
    PermissionSet,
    PermissionSetHolder,
    PermissionSetPermission,
    Region,
    RegionGrant,
    Team,
    TeamMember,
    TeamParent,
    Tracker,
    TrackerRole,
    User,
)

BASE_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost/tracker_test")
# Under pytest-xdist each worker (gw0, gw1, ...) gets its own database, tracker_test_gw0 and so on, because every test
# empties the database it uses when it ends. A run without -n keeps tracker_test.
WORKER = os.environ.get("PYTEST_XDIST_WORKER")
DATABASE_URL = (
    make_url(BASE_DATABASE_URL)
    .set(database=f"{make_url(BASE_DATABASE_URL).database}_{WORKER}")
    .render_as_string(hide_password=False)
    if WORKER
    else BASE_DATABASE_URL
)
ROOT = Path(__file__).resolve().parent.parent

_state: dict = {}


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    """Keep a developer's untracked .env (for example SESSION_COOKIE_SECURE=false) out of the configuration tests."""
    monkeypatch.setattr("tracker.config.load_dotenv", lambda *args, **kwargs: False)


@pytest.fixture
def app():
    """A fresh app per test. Its connection pool is closed when the test ends: left to the garbage collector, the
    pools of several parallel workers together exceed the server's connection limit."""
    application = create_app(
        {"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": DATABASE_URL, "SESSION_COOKIE_SECURE": False}
    )
    yield application
    get_engine(application).dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_worker_database() -> None:
    """Create this worker's database (through the server's ``postgres`` database) when it does not exist yet."""
    url = make_url(DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
            if exists.scalar() is None:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def _db_engine():
    """Probe the database once; migrate once; skip the dependent tests when it is unreachable."""
    if "engine" not in _state:
        engine = create_engine(DATABASE_URL)
        try:
            if WORKER:
                _create_worker_database()
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            engine.dispose()
            _state["engine"] = None
        else:
            command.upgrade(alembic_config(), "head")
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


@functools.cache
def hashed_test_password() -> str:
    """Every test user has TEST_PASSWORD; bcrypt takes about 0.2 s, so it is hashed once per run, not per user."""
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def user_factory(db):
    counter = {"n": 0}

    def make(**overrides) -> User:
        counter["n"] += 1
        values = {
            "email": f"user{counter['n']}@example.com",
            "full_name": f"User {counter['n']}",
            "password_hash": hashed_test_password(),
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


@pytest.fixture
def region_factory(db):
    def make(code: str = "EMEA", name: str | None = None, retired: bool = False) -> Region:
        region = Region(code=code, name=name or f"{code} region", retired=retired)
        db.add(region)
        db.commit()
        return region

    return make


_location_codes = itertools.count()


def _next_location_code() -> str:
    n = next(_location_codes)
    return "Q" + "".join(string.ascii_uppercase[(n // 26**i) % 26] for i in (1, 0))


@pytest.fixture
def location_factory(db):
    def make(
        region: Region, city: str = "Geneva", country_code: str = "CH", code: str | None = None, retired: bool = False
    ) -> Location:
        if code is None:  # a letters-only code per call, QAA, QAB, ..., never a real-looking one such as LON
            code = _next_location_code()
        location = Location(region_id=region.id, city=city, country_code=country_code, code=code, retired=retired)
        db.add(location)
        db.commit()
        return location

    return make


@pytest.fixture
def business_line_factory(db):
    def make(name: str = "Tradition brokerage", retired: bool = False) -> BusinessLine:
        line = BusinessLine(name=name, retired=retired)
        db.add(line)
        db.commit()
        return line

    return make


@pytest.fixture
def labels_form(region_factory, business_line_factory) -> dict:
    """A business line and a region, as the New tracker, Settings and import-confirm forms post them."""
    line, region = business_line_factory(), region_factory()
    return {"business_line_id": str(line.id), "region_ids": [str(region.id)]}


@pytest.fixture
def team_factory(db):
    counter = {"n": 0}

    def make(name: str | None = None, parent: Team | None = None, parents: tuple[Team, ...] = (), **kw) -> Team:
        """A team below ``parent`` and below each team in ``parents`` (top level without either)."""
        if name is None:
            counter["n"] += 1
            name = f"Team {counter['n']}"
        if kw.get("location_id") and "region_id" not in kw:  # a team's region is its location's region
            kw["region_id"] = db.get(Location, kw["location_id"]).region_id
        team = Team(name=name, **kw)
        db.add(team)
        db.flush()
        higher = ([parent] if parent else []) + list(parents)
        db.add_all(TeamParent(team_id=team.id, parent_id=other.id) for other in higher)
        db.commit()
        return team

    return make


@pytest.fixture
def add_member(db):
    def add(team: Team, user: User, role: str) -> None:
        db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
        db.commit()

    return add


@pytest.fixture
def give_set(db):
    counter = {"n": 0}

    def give(
        permissions: list[str], *, team: Team | None = None, user: User | None = None, name: str | None = None
    ) -> PermissionSet:
        if name is None:
            counter["n"] += 1
            name = f"Set {counter['n']}"
        permission_set = PermissionSet(name=name)
        db.add(permission_set)
        db.flush()
        db.add_all(PermissionSetPermission(set_id=permission_set.id, permission=p) for p in permissions)
        db.add(
            PermissionSetHolder(
                set_id=permission_set.id, team_id=team.id if team else None, user_id=user.id if user else None
            )
        )
        db.commit()
        return permission_set

    return give


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


@pytest.fixture
def region_grant(db):
    def give(region: Region, user: User, role: str) -> None:
        db.add(RegionGrant(region_id=region.id, user_id=user.id, role=role))
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


# --- Live server and browser (Playwright) ------------------------------------------------------------------------


@pytest.fixture
def live_server(app, _db_engine):
    """The application served on a free local port in a background thread, for browser tests."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def browser():
    """A Chromium per test: one kept open across tests would clash with the app's own Playwright session, which
    renders the PDF and PNG (Playwright allows one sync session per thread)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        try:
            yield chromium
        finally:
            chromium.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


def browser_sign_in(page, base_url: str, user: User) -> None:
    page.goto(f"{base_url}/login")
    page.fill("input[name=email]", user.email)
    page.fill("input[name=password]", TEST_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
