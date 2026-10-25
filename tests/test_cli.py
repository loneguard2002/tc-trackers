"""Command-line interface, deployment blueprint and Alembic environment checks."""

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from tracker.auth.passwords import hash_password, verify_password
from tracker.models import AuditLog, User

ROOT = Path(__file__).resolve().parent.parent


def test_alembic_requires_an_explicit_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    config = Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with pytest.raises(RuntimeError, match="Set DATABASE_URL"):
        command.upgrade(config, "head", sql=True)


def test_alembic_reads_database_url_from_the_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/offline")
    buffer = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head", sql=True)
    assert "CREATE TABLE users" in buffer.getvalue()


def test_render_blueprint_defines_web_and_worker_without_secret_values():
    import yaml

    raw = (ROOT / "render.yaml").read_text()
    uncommented = "\n".join(line.split("#", 1)[0] for line in raw.splitlines())
    assert "&" not in uncommented and "*" not in uncommented  # no YAML anchors or aliases
    blueprint = yaml.safe_load(raw)
    services = {service["name"]: service for service in blueprint["services"]}
    web, worker = services["tracker-web"], services["tracker-worker"]
    assert web["type"] == "web" and web["runtime"] == "docker"
    assert web["preDeployCommand"] == "alembic upgrade head"
    assert web["healthCheckPath"] == "/healthz"
    assert worker["type"] == "worker" and worker["runtime"] == "docker"
    assert worker["dockerCommand"] == 'flask --app "tracker.app:create_app()" run-scheduler --interval 60'
    required = {
        "DATABASE_URL",
        "FLASK_SECRET_KEY",
        "APP_URL",
        "SMTP_PASSWORD",
        "SMTP_CLIENT_SECRET",
        "SSO_TENANT_ID",
        "SSO_CLIENT_ID",
        "SSO_CLIENT_SECRET",
    }
    for service in (web, worker):
        variables = {item["key"]: item for item in service["envVars"]}
        assert required <= set(variables)
        for item in variables.values():
            assert item.get("sync") is False
            assert "value" not in item
        assert "SESSION_COOKIE_SECURE" not in variables


@pytest.mark.db
def test_run_scheduler_once_exits_cleanly_with_no_trackers(app, db):
    result = app.test_cli_runner().invoke(args=["run-scheduler", "--once"])
    assert result.exit_code == 0, result.output
    assert "0 send(s) attempted" in result.output


@pytest.mark.db
def test_create_admin_creates_an_active_administrator(app, db):
    result = app.test_cli_runner().invoke(args=["create-admin", "a@example.com", "--password", "a-long-password-1"])
    assert result.exit_code == 0, result.output
    user = db.scalars(select(User).where(User.email == "a@example.com")).one()
    assert user.status == "active" and user.is_admin and user.auth_source == "local"
    assert verify_password("a-long-password-1", user.password_hash)


def _local_user(db, email="u@example.com", password="old-password-123", **overrides) -> User:
    values = {
        "email": email,
        "full_name": "U",
        "password_hash": hash_password(password),
        "auth_source": "local",
        "status": "active",
    }
    values.update(overrides)
    user = User(**values)
    db.add(user)
    db.commit()
    return user


@pytest.mark.db
def test_reset_password_with_option_replaces_hash_and_audits_without_the_password(app, db):
    user = _local_user(db)
    result = app.test_cli_runner().invoke(args=["reset-password", "U@Example.com", "--password", "new-password-456"])
    assert result.exit_code == 0, result.output
    db.expire_all()
    assert verify_password("new-password-456", db.get(User, user.id).password_hash)
    row = db.scalars(select(AuditLog).where(AuditLog.action == "password_reset")).one()
    assert row.entity == "user" and row.entity_id == str(user.id) and row.user_id is None
    assert "new-password-456" not in repr(row.detail) and "password" not in (row.detail or {})
    assert "new-password-456" not in result.output


@pytest.mark.db
def test_reset_password_prompts_with_confirmation_when_option_omitted(app, db):
    user = _local_user(db)
    result = app.test_cli_runner().invoke(
        args=["reset-password", "u@example.com"], input="prompted-pass-789\nprompted-pass-789\n"
    )
    assert result.exit_code == 0, result.output
    db.expire_all()
    assert verify_password("prompted-pass-789", db.get(User, user.id).password_hash)


@pytest.mark.db
def test_reset_password_rejects_short_password_and_leaves_hash_unchanged(app, db):
    user = _local_user(db)
    result = app.test_cli_runner().invoke(args=["reset-password", "u@example.com", "--password", "short"])
    assert result.exit_code != 0 and "at least" in result.output
    db.expire_all()
    assert verify_password("old-password-123", db.get(User, user.id).password_hash)


@pytest.mark.db
def test_reset_password_unknown_email_is_a_clear_error(app, db):
    result = app.test_cli_runner().invoke(
        args=["reset-password", "nobody@example.com", "--password", "new-password-456"]
    )
    assert result.exit_code != 0 and "No user with the email nobody@example.com" in result.output


@pytest.mark.db
def test_reset_password_refuses_single_sign_on_accounts(app, db):
    _local_user(db, email="s@example.com", password_hash=None, auth_source="sso", sso_subject="subject-1")
    result = app.test_cli_runner().invoke(args=["reset-password", "s@example.com", "--password", "new-password-456"])
    assert result.exit_code != 0 and "single sign-on" in result.output


def test_stuck_send_queries_carry_an_age_guard():
    for name in ("README.md", "docs/runbooks/deploy-render.md"):
        text = (ROOT / name).read_text()
        assert "created_at < now() - interval '15 minutes'" in text
    runbook = (ROOT / "docs/runbooks/deploy-render.md").read_text()
    assert runbook.count("interval '15 minutes'") == 2
