from alembic import command
from conftest import alembic_config
from sqlalchemy import inspect, text


def test_upgrade_gives_teams_their_location_region(db, region_factory, location_factory):
    emea = region_factory("EMEA")
    geneva = location_factory(emea)
    try:
        command.downgrade(alembic_config(), "0007")
        assert "region_id" not in {c["name"] for c in inspect(db.connection()).get_columns("teams")}
        db.execute(
            text("INSERT INTO teams (name, location_id) VALUES ('Placed', :id), ('Unplaced', NULL)"), {"id": geneva.id}
        )
        db.commit()
        command.upgrade(alembic_config(), "head")
        rows = dict(db.execute(text("SELECT name, region_id FROM teams")).all())
        assert rows == {"Placed": emea.id, "Unplaced": None}
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
