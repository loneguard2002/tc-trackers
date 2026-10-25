"""Alembic environment; the URL comes from DATABASE_URL or TEST_DATABASE_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from tracker.config import normalise_database_url
from tracker.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = (
        config.get_main_option("sqlalchemy.url")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("TEST_DATABASE_URL")
    )
    if not url:
        raise RuntimeError("Set DATABASE_URL (or TEST_DATABASE_URL for tests) before running Alembic.")
    return normalise_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
