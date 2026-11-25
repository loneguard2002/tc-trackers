"""The sign-in limiter counts in the database: shared by every worker and instance, and kept across a restart."""

from datetime import timedelta

from conftest import TEST_PASSWORD, post
from sqlalchemy import func, select

from tracker.app import create_app
from tracker.auth import throttle
from tracker.auth.throttle import KEEP_FAILURES, Limits
from tracker.db import get_engine
from tracker.models import AppSetting, LoginFailure


def _rows(db) -> set[tuple[str, str]]:
    return set(db.execute(select(LoginFailure.kind, LoginFailure.value)).all())


def test_blocks_after_attempts_and_clears(db):
    limits = Limits(account_attempts=5)
    for _ in range(4):
        throttle.fail(db, "account", "k@example.com")
    assert not throttle.blocked(db, limits, "account", "k@example.com")
    throttle.fail(db, "account", "k@example.com")
    assert throttle.blocked(db, limits, "account", "k@example.com")
    assert not throttle.blocked(db, limits, "account", "other@example.com")
    assert not throttle.blocked(db, limits, "address", "k@example.com")  # the kinds are counted apart
    assert throttle.clear(db, "account", "k@example.com") == 5
    assert not throttle.blocked(db, limits, "account", "k@example.com")


def test_failures_outside_the_window_do_not_count(db):
    limits = Limits(account_attempts=3, window_minutes=5)
    for _ in range(3):
        db.add(LoginFailure(kind="account", value="k", at=func.now() - timedelta(minutes=5, seconds=1)))
    db.flush()
    assert not throttle.blocked(db, limits, "account", "k")
    for _ in range(3):
        throttle.fail(db, "account", "k")
    assert throttle.blocked(db, limits, "account", "k")


def test_a_new_failure_deletes_those_older_than_a_day(db):
    db.add(LoginFailure(kind="account", value="old", at=func.now() - KEEP_FAILURES - timedelta(minutes=1)))
    db.add(LoginFailure(kind="account", value="recent", at=func.now() - timedelta(hours=1)))
    db.flush()
    throttle.fail(db, "address", "10.0.0.1")
    assert _rows(db) == {("account", "recent"), ("address", "10.0.0.1")}


def test_a_failed_sign_in_counts_the_account_and_the_address(client, db, user_factory):
    user = user_factory()
    post(client, "/login", {"email": user.email, "password": "wrong-password"})
    assert _rows(db) == {("account", user.email), ("address", "127.0.0.1")}


def test_a_blank_email_counts_only_the_address(client, db):
    post(client, "/login", {"email": "", "password": "wrong-password"})
    assert _rows(db) == {("address", "127.0.0.1")}


def test_failures_in_one_instance_block_sign_in_in_another(app, db, user_factory):
    """Two app instances stand for two Gunicorn workers, or the app before and after a restart."""
    user = user_factory()
    first = app.test_client()
    for _ in range(5):
        post(first, "/login", {"email": user.email, "password": "wrong-password"})
    other_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE_URL": app.config["DATABASE_URL"],
            "SESSION_COOKIE_SECURE": False,
        }
    )
    try:
        response = post(other_app.test_client(), "/login", {"email": user.email, "password": TEST_PASSWORD})
        assert response.status_code == 429
    finally:
        get_engine(other_app).dispose()


def test_a_successful_sign_in_clears_the_account_count(client, db, user_factory):
    user = user_factory()
    for _ in range(4):
        post(client, "/login", {"email": user.email, "password": "wrong-password"})
    post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert _rows(db) == {("address", "127.0.0.1")}  # the address keeps its count


def test_saved_limits_apply_to_the_next_attempt(client, db, user_factory):
    db.add(AppSetting(key="login_account_attempts", value="3"))
    db.commit()
    user = user_factory()
    for _ in range(3):
        post(client, "/login", {"email": user.email, "password": "wrong-password"})
    assert post(client, "/login", {"email": user.email, "password": TEST_PASSWORD}).status_code == 429


def test_unreadable_saved_limits_fall_back_to_the_defaults(db):
    db.add_all(
        [
            AppSetting(key="login_account_attempts", value="abc"),
            AppSetting(key="login_address_attempts", value="1"),  # below the lowest allowed
            AppSetting(key="login_window_minutes", value="10"),
        ]
    )
    db.flush()
    assert throttle.load_limits(db) == Limits(account_attempts=5, address_attempts=20, window_minutes=10)


def test_summaries_say_who_is_blocked_and_until_when(db):
    limits = Limits(account_attempts=3, window_minutes=5)
    for minutes_ago in (4, 3, 2, 1):
        db.add(LoginFailure(kind="account", value="a@example.com", at=func.now() - timedelta(minutes=minutes_ago)))
    db.add(LoginFailure(kind="account", value="b@example.com", at=func.now() - timedelta(minutes=1)))
    db.add(LoginFailure(kind="account", value="c@example.com", at=func.now() - timedelta(hours=2)))
    db.flush()
    now, rows = throttle.summaries(db, limits)
    by_value = {row.value: row for row in rows}
    assert [row.value for row in rows][0] == "a@example.com"  # blocked first
    a = by_value["a@example.com"]
    # four in the window, limit three: blocked until the two oldest have left it, at (3 minutes ago + 5 minutes)
    assert a.blocked and a.in_window == 4 and a.last_day == 4
    assert abs((a.unblocks_at - (now + timedelta(minutes=2))).total_seconds()) < 2
    assert not by_value["b@example.com"].blocked and by_value["b@example.com"].left == 2
    c = by_value["c@example.com"]
    assert (c.in_window, c.last_day, c.blocked) == (0, 1, False)
    assert throttle.blocked_count(db, limits) == 1


def test_parse_limits_checks_each_range():
    limits, errors = throttle.parse_limits({"account_attempts": "4", "address_attempts": "30", "window_minutes": "15"})
    assert limits == Limits(4, 30, 15) and errors == {}
    limits, errors = throttle.parse_limits({"account_attempts": "2", "address_attempts": "x", "window_minutes": "61"})
    assert limits is None and set(errors) == {"account_attempts", "address_attempts", "window_minutes"}
