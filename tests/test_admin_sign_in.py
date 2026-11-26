"""Admin › Sign-in protection: the limits, who is blocked, the last day's failures, unblocking."""

from datetime import timedelta

import pytest
from conftest import TEST_PASSWORD, post
from sqlalchemy import func, select

from tracker.models import AppSetting, AuditLog, LoginFailure

PAGE = "/admin/sign-in-protection"


def _fail(db, kind: str, value: str, times: int, minutes_ago: float = 1) -> None:
    for _ in range(times):
        db.add(LoginFailure(kind=kind, value=value, at=func.now() - timedelta(minutes=minutes_ago)))
    db.commit()


def _audit(db, action: str) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_anonymous_people_go_to_sign_in(client, db):
    response = client.get(PAGE)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", [PAGE, PAGE + "/unblock"])
def test_people_without_the_permission_are_refused(client, logged_in_user, path):
    response = post(client, path, {"kind": "account", "value": "x"}) if path.endswith("unblock") else client.get(path)
    assert response.status_code == 403


def test_the_page_shows_the_limits_and_who_is_blocked(client, db, logged_in_admin):
    _fail(db, "account", "blocked@example.com", 5)
    _fail(db, "address", "10.0.4.17", 2)
    html = client.get(PAGE).get_data(as_text=True)
    assert "Sign-in protection" in html
    assert "blocked@example.com" in html and "10.0.4.17" in html
    assert "5 of 5" in html and "2 of 20" in html
    assert "Blocked until" in html and "18 left" in html
    assert 'value="5"' in html and 'value="20"' in html  # the limits form shows the saved values


def test_the_menu_counts_who_is_blocked_for_administrators(client, db, logged_in_admin):
    _fail(db, "account", "blocked@example.com", 5)
    html = client.get("/").get_data(as_text=True)
    assert "Sign-in protection" in html and "blocked now" in html


def test_the_menu_link_is_only_for_those_who_may_open_the_page(client, logged_in_user):
    assert "Sign-in protection" not in client.get("/").get_data(as_text=True)


def test_the_permission_opens_the_page_and_the_menu_link(client, db, logged_in_user, give_set):
    give_set(["manage_sign_in_protection"], user=logged_in_user)
    _fail(db, "account", "blocked@example.com", 5)
    assert client.get(PAGE).status_code == 200
    html = client.get("/").get_data(as_text=True)
    assert "Sign-in protection" in html and "blocked now" in html


def test_a_holder_of_the_permission_can_unblock_and_change_the_limits(client, db, logged_in_user, give_set):
    give_set(["manage_sign_in_protection"], user=logged_in_user)
    _fail(db, "account", "blocked@example.com", 5)
    post(client, PAGE + "/unblock", {"kind": "account", "value": "blocked@example.com"})
    assert db.scalar(select(func.count()).select_from(LoginFailure)) == 0
    assert _audit(db, "sign_in_unblocked")[0].user_id == logged_in_user.id
    post(
        client,
        PAGE,
        {"account_attempts": "7", "address_attempts": "20", "window_minutes": "5", "downloads_per_minute": "10"},
    )
    assert _audit(db, "sign_in_limits_changed")[0].user_id == logged_in_user.id


def test_an_empty_page_says_so(client, db, logged_in_admin):
    html = client.get(PAGE).get_data(as_text=True)
    assert "No account or address is blocked." in html and "No failed sign-ins in the last 24 hours." in html


def test_unblock_clears_the_failures_and_is_recorded(client, db, user_factory, logged_in_admin):
    user = user_factory(email="locked@example.com")
    _fail(db, "account", user.email, 5)
    person = client.application.test_client()  # the locked-out person, in another browser; ``client`` is the admin
    assert post(person, "/login", {"email": user.email, "password": TEST_PASSWORD}).status_code == 429
    response = post(client, PAGE + "/unblock", {"kind": "account", "value": user.email})
    assert response.status_code == 302
    assert db.scalar(select(func.count()).select_from(LoginFailure).where(LoginFailure.kind == "account")) == 0
    (entry,) = _audit(db, "sign_in_unblocked")
    assert entry.user_id == logged_in_admin.id
    assert entry.detail == {"account": user.email, "failures_cleared": 5}
    assert post(person, "/login", {"email": user.email, "password": TEST_PASSWORD}).status_code == 302


def test_unblocking_what_has_no_failures_changes_nothing(client, db, logged_in_admin):
    response = post(client, PAGE + "/unblock", {"kind": "address", "value": "10.9.9.9"}, follow_redirects=True)
    assert "has no failed sign-ins to clear" in response.get_data(as_text=True)
    assert _audit(db, "sign_in_unblocked") == []


@pytest.mark.parametrize("data", [{"kind": "other", "value": "x"}, {"kind": "account", "value": ""}])
def test_unblock_refuses_a_bad_request(client, logged_in_admin, data):
    assert post(client, PAGE + "/unblock", data).status_code == 400


def test_saving_the_limits_stores_and_records_them(client, db, logged_in_admin):
    data = {"account_attempts": "4", "address_attempts": "20", "window_minutes": "10", "downloads_per_minute": "10"}
    assert post(client, PAGE, data).status_code == 302
    stored = dict(db.execute(select(AppSetting.key, AppSetting.value)).all())
    assert stored["login_account_attempts"] == "4" and stored["login_window_minutes"] == "10"
    (entry,) = _audit(db, "sign_in_limits_changed")
    assert entry.detail == {
        "before": {"account_attempts": 5, "window_minutes": 5},
        "after": {"account_attempts": 4, "window_minutes": 10},
    }


def test_unchanged_limits_are_not_recorded(client, db, logged_in_admin):
    data = {"account_attempts": "5", "address_attempts": "20", "window_minutes": "5", "downloads_per_minute": "10"}
    response = post(client, PAGE, data, follow_redirects=True)
    assert "The limits are unchanged." in response.get_data(as_text=True)
    assert _audit(db, "sign_in_limits_changed") == []


def test_limits_out_of_range_are_refused_and_nothing_is_saved(client, db, logged_in_admin):
    data = {"account_attempts": "1", "address_attempts": "20", "window_minutes": "5", "downloads_per_minute": "10"}
    response = post(client, PAGE, data)
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Enter a whole number from 3 to 50." in html and 'aria-invalid="true"' in html
    assert db.scalar(select(func.count()).select_from(AppSetting).where(AppSetting.key.like("login_%"))) == 0


def _limits(**changes) -> dict[str, str]:
    return {
        "account_attempts": "5",
        "address_attempts": "20",
        "window_minutes": "5",
        "downloads_per_minute": "10",
    } | changes


def test_the_page_shows_the_download_limit(client, logged_in_admin):
    html = client.get(PAGE).get_data(as_text=True)
    assert "Report downloads" in html and 'name="downloads_per_minute"' in html and 'value="10"' in html


def test_saving_the_download_limit_stores_and_records_only_it(client, db, logged_in_admin):
    response = post(client, PAGE, _limits(downloads_per_minute="4"), follow_redirects=True)
    assert "Limits saved." in response.get_data(as_text=True)
    assert db.scalar(select(AppSetting.value).where(AppSetting.key == "export_downloads_per_minute")) == "4"
    (entry,) = _audit(db, "download_limit_changed")
    assert entry.user_id == logged_in_admin.id
    assert entry.detail == {"before": {"per_minute": 10}, "after": {"per_minute": 4}}
    assert _audit(db, "sign_in_limits_changed") == []
    assert 'value="4"' in client.get(PAGE).get_data(as_text=True)


@pytest.mark.parametrize("value", ["0", "61", "ten", ""])
def test_a_download_limit_out_of_range_is_refused_and_nothing_is_saved(client, db, logged_in_admin, value):
    response = post(client, PAGE, _limits(account_attempts="4", downloads_per_minute=value))
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Enter a whole number from 1 to 60." in html and 'id="downloads_per_minute-error"' in html
    assert db.scalar(select(func.count()).select_from(AppSetting).where(AppSetting.key.like("login_%"))) == 0
