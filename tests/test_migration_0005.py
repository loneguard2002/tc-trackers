import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import select, text

from tracker.models import Location


@pytest.fixture
def at_revision_0004(db):
    command.downgrade(alembic_config(), "0004")
    try:
        yield
    finally:
        db.rollback()
        db.execute(text("DELETE FROM locations"))
        db.execute(text("DELETE FROM regions"))
        db.commit()
        command.upgrade(alembic_config(), "head")


def _region(db, code) -> int:
    return db.execute(
        text("INSERT INTO regions (code, name) VALUES (:c, :n) RETURNING id"), {"c": code, "n": f"{code} region"}
    ).scalar_one()


def _location(db, region_id, city, country) -> int:
    return db.execute(
        text("INSERT INTO locations (region_id, city, country) VALUES (:r, :city, :country) RETURNING id"),
        {"r": region_id, "city": city, "country": country},
    ).scalar_one()


def test_upgrade_converts_typed_countries(db, at_revision_0004):
    region = _region(db, "EMEA")
    rows = {
        city: _location(db, region, city, country)
        for city, country in [
            ("London", "United Kingdom"),
            ("Leeds", "uk"),
            ("Dubai", "UAE"),
            ("Atlantis", "Atlantis"),
        ]
    }
    db.commit()
    command.upgrade(alembic_config(), "head")
    got = {city: db.get(Location, i).country_code for city, i in rows.items()}
    assert got == {"London": "GB", "Leeds": "GB", "Dubai": "AE", "Atlantis": None}
    assert all(db.get(Location, i).code is None for i in rows.values())


def test_upgrade_refuses_two_rows_that_become_the_same_place(db, at_revision_0004):
    region = _region(db, "EMEA")
    _location(db, region, "London", "United Kingdom")
    _location(db, region, "london", "UK")
    db.commit()
    with pytest.raises(RuntimeError, match="London"):
        command.upgrade(alembic_config(), "head")
    # The refusal leaves the database as it was: still at 0004, with the typed countries.
    db.rollback()
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
    got = sorted(db.execute(text("SELECT city, country FROM locations")).all())
    assert got == [("London", "United Kingdom"), ("london", "UK")]


def test_downgrade_restores_country_names(db):
    region = _region(db, "EMEA")
    db.execute(
        text("INSERT INTO locations (region_id, city, code, country_code) VALUES (:r, 'London', 'LON', 'GB')"),
        {"r": region},
    )
    db.execute(text("INSERT INTO locations (region_id, city) VALUES (:r, 'Nowhere')"), {"r": region})
    db.commit()
    try:
        command.downgrade(alembic_config(), "0004")
        got = dict(db.execute(text("SELECT city, country FROM locations")).all())
        assert got == {"London": "United Kingdom", "Nowhere": ""}
    finally:
        db.rollback()
        db.execute(text("DELETE FROM locations"))
        db.execute(text("DELETE FROM regions"))
        db.commit()
        command.upgrade(alembic_config(), "head")
    assert db.scalars(select(Location)).all() == []
