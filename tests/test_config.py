"""Database-free configuration tests."""

from __future__ import annotations

import pytest

from tracker.config import load_config, normalise_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db?sslmode=require", "postgresql+psycopg://u:p@h:5432/db?sslmode=require"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg2://u@h/db", "postgresql+psycopg2://u@h/db"),
        ("", ""),
    ],
)
def test_normalise_database_url(raw, expected):
    assert normalise_database_url(raw) == expected


def test_load_config_normalises_override_and_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u@h/db")
    assert load_config()["DATABASE_URL"] == "postgresql+psycopg://u@h/db"
    assert load_config({"DATABASE_URL": "postgresql://x@y/z"})["DATABASE_URL"] == "postgresql+psycopg://x@y/z"


def test_alembic_url_is_normalised(monkeypatch):
    import importlib.util
    from pathlib import Path
    from unittest import mock

    from alembic import context

    monkeypatch.setenv("DATABASE_URL", "postgres://u@h/db")
    fake = mock.MagicMock()
    fake.get_main_option.return_value = ""
    fake.config_file_name = None
    with mock.patch.object(context, "config", fake, create=True):
        spec = importlib.util.spec_from_file_location(
            "alembic_env_under_test", Path(__file__).resolve().parent.parent / "migrations" / "env.py"
        )
        module = importlib.util.module_from_spec(spec)
        with (
            mock.patch.object(context, "is_offline_mode", return_value=True),
            mock.patch.object(context, "configure"),
            mock.patch.object(context, "begin_transaction"),
            mock.patch.object(context, "run_migrations"),
        ):
            spec.loader.exec_module(module)
        assert module._url() == "postgresql+psycopg://u@h/db"
