"""Authentication, approval and administration (database required)."""

from conftest import TEST_PASSWORD, post
from sqlalchemy import select

from tracker.models import AppSetting, AuditLog, User


def test_local_login_success(client, user_factory):
    user = user_factory()
    response = post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    with client.session_transaction() as sess:
        assert sess["user_id"] == user.id
        assert "is_admin" not in sess


def test_login_email_is_case_insensitive(client, user_factory):
    user = user_factory()
    response = post(client, "/login", {"email": user.email.upper(), "password": TEST_PASSWORD})
    assert response.status_code == 302


def test_wrong_password_rejected(client, user_factory):
    user = user_factory()
    response = post(client, "/login", {"email": user.email, "password": "wrong"})
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_pending_user_cannot_log_in(client, user_factory):
    user = user_factory(status="pending")
    response = post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert b"awaiting approval" in response.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_disabled_user_cannot_log_in(client, user_factory):
    user = user_factory(status="disabled")
    response = post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_sso_user_without_password_cannot_use_local_login(client, user_factory):
    user = user_factory(auth_source="sso", password_hash=None)
    response = post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert b"Invalid email or password" in response.data


def test_login_throttled_after_5_failures(client, user_factory):
    user = user_factory()
    for _ in range(5):
        post(client, "/login", {"email": user.email, "password": "wrong"})
    response = post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 429
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_honours_safe_next_only(client, user_factory):
    user = user_factory()
    response = post(client, "/login?next=/trackers/3", {"email": user.email, "password": TEST_PASSWORD})
    assert response.headers["Location"] == "/trackers/3"
    client2 = client.application.test_client()
    response = post(client2, "/login?next=//evil.example", {"email": user.email, "password": TEST_PASSWORD})
    assert response.headers["Location"] == "/"


def test_logout_clears_session(client, logged_in_user):
    response = post(client, "/logout")
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_session_is_permanent_after_login(client, user_factory):
    user = user_factory()
    post(client, "/login", {"email": user.email, "password": TEST_PASSWORD})
    cookie = client.get_cookie("session")
    assert cookie is not None and cookie.expires is not None


def test_disabled_user_session_treated_as_logged_out(client, logged_in_user, db):
    db.get(User, logged_in_user.id).status = "disabled"
    db.commit()
    response = client.get("/")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_post_without_csrf_rejected(client, logged_in_admin):
    assert client.post("/admin/users/1/approve").status_code == 400
    assert client.post("/admin/users/1/approve", data={"csrf_token": "wrong"}).status_code == 400


def test_admin_approves_pending_user(client, logged_in_admin, user_factory, db):
    pending = user_factory(status="pending")
    response = post(client, f"/admin/users/{pending.id}/approve")
    assert response.status_code == 302
    db.expire_all()
    assert db.get(User, pending.id).status == "active"
    row = db.scalars(select(AuditLog).where(AuditLog.action == "user_approved")).one()
    assert row.user_id == logged_in_admin.id and row.entity_id == str(pending.id)


def test_admin_disables_user_but_not_self(client, logged_in_admin, user_factory, db):
    other = user_factory()
    post(client, f"/admin/users/{other.id}/disable")
    post(client, f"/admin/users/{logged_in_admin.id}/disable")
    db.expire_all()
    assert db.get(User, other.id).status == "disabled"
    assert db.get(User, logged_in_admin.id).status == "active"


def test_admin_grants_and_revokes_admin_but_not_self(client, logged_in_admin, user_factory, db):
    other = user_factory()
    post(client, f"/admin/users/{other.id}/admin", {"is_admin": "1"})
    db.expire_all()
    assert db.get(User, other.id).is_admin is True
    post(client, f"/admin/users/{other.id}/admin", {"is_admin": "0"})
    post(client, f"/admin/users/{logged_in_admin.id}/admin", {"is_admin": "0"})
    db.expire_all()
    assert db.get(User, other.id).is_admin is False
    assert db.get(User, logged_in_admin.id).is_admin is True


def test_admin_creates_active_local_user(client, logged_in_admin, db):
    response = post(
        client,
        "/admin/users",
        {"email": "New.Person@example.com", "full_name": "New Person", "password": "a long enough password"},
    )
    assert response.status_code == 302
    created = db.scalars(select(User).where(User.email == "new.person@example.com")).one()
    assert created.status == "active" and created.auth_source == "local" and created.password_hash


def test_add_user_has_its_own_page(client, logged_in_admin, db, user_factory):
    assert 'href="/admin/users/new"' in client.get("/admin/users").get_data(as_text=True)
    page = client.get("/admin/users/new")
    assert page.status_code == 200 and b'name="password"' in page.data
    short = post(client, "/admin/users", {"email": "kept@example.com", "full_name": "Kept Name", "password": "short"})
    assert short.status_code == 400
    assert b"Please correct the following" in short.data
    assert b'value="Kept Name"' in short.data and b'value="kept@example.com"' in short.data
    taken = user_factory()
    form = {"email": taken.email, "full_name": "Someone", "password": "a long enough password"}
    duplicate = post(client, "/admin/users", form)
    assert duplicate.status_code == 400 and b"A user with that email address already exists." in duplicate.data


def test_non_admin_cannot_open_add_user(client, logged_in_user):
    assert client.get("/admin/users/new").status_code == 403


def test_admin_user_list_renders(client, logged_in_admin, user_factory):
    user_factory(status="pending", full_name="Waiting Person")
    response = client.get("/admin/users")
    assert response.status_code == 200 and b"Waiting Person" in response.data


def test_admin_user_list_offers_actions_per_person(client, logged_in_admin, user_factory):
    pending = user_factory(full_name="Waiting Person", status="pending")
    html = client.get("/admin/users").get_data(as_text=True)
    assert f'action="/admin/users/{pending.id}/approve"' in html
    assert "1 awaiting approval" in html
    assert 'data-confirm="Disable Waiting Person?' in html
    assert f'action="/admin/users/{logged_in_admin.id}/disable"' not in html  # never your own account


def test_non_admin_cannot_open_admin(client, logged_in_user):
    assert client.get("/admin/users").status_code == 403
    assert client.get("/admin/smtp").status_code == 403
    assert post(client, "/admin/users/1/approve").status_code == 403


def test_admin_link_visible_only_to_admins(client, logged_in_admin, user_factory):
    assert b'href="/admin/users"' in client.get("/").data
    other = client.application.test_client()
    from conftest import sign_in

    sign_in(other, user_factory())
    assert b'href="/admin/users"' not in other.get("/").data


def test_smtp_settings_saved_without_secrets(client, logged_in_admin, db):
    response = post(
        client,
        "/admin/smtp",
        {
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_auth": "xoauth2",
            "smtp_user": "reports@example.com",
            "smtp_from": "reports@example.com",
            "smtp_tenant_id": "tenant",
            "smtp_client_id": "client",
            "SMTP_PASSWORD": "must-not-be-stored",
            "smtp_client_secret": "must-not-be-stored",
        },
    )
    assert response.status_code == 302
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    assert stored["smtp_host"] == "smtp.example.com" and stored["smtp_auth"] == "xoauth2"
    assert all("must-not-be-stored" not in value for value in stored.values())
    assert not any("secret" in key or "password" in key for key in stored)
    assert client.get("/admin/smtp").status_code == 200


def test_smtp_rejects_invalid_values(client, logged_in_admin, db):
    response = post(client, "/admin/smtp", {"smtp_host": "h", "smtp_port": "abc", "smtp_auth": "plain"})
    assert response.status_code == 400
    response = post(client, "/admin/smtp", {"smtp_host": "h", "smtp_port": "25", "smtp_auth": "weird"})
    assert response.status_code == 400
    assert db.scalars(select(AppSetting)).first() is None
