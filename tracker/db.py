"""Database engine and request-scoped session handling."""

from __future__ import annotations

from flask import Flask, current_app, g
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_EXTENSION_KEY = "tracker_db"


def init_db(app: Flask) -> None:
    """Create the engine (lazily connecting) and register session teardown."""
    engine = create_engine(app.config["DATABASE_URL"], pool_pre_ping=True)
    app.extensions[_EXTENSION_KEY] = {"engine": engine, "factory": sessionmaker(engine, expire_on_commit=False)}
    app.teardown_appcontext(_close_session)


def get_engine(app: Flask | None = None) -> Engine:
    return (app or current_app).extensions[_EXTENSION_KEY]["engine"]


def get_session() -> Session:
    """Return the session for the current request, creating it on first use."""
    if "db_session" not in g:
        g.db_session = current_app.extensions[_EXTENSION_KEY]["factory"]()
    return g.db_session


def _close_session(_exc: BaseException | None = None) -> None:
    session = g.pop("db_session", None)
    if session is not None:
        session.close()
