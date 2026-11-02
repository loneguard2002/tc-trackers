import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import func, select, text

from tracker.models import BusinessLine, Region, Team, Tracker, TrackerRegion


@pytest.fixture
def at_revision_0003(db):
    command.downgrade(alembic_config(), "0003")
    try:
        yield
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")


def _insert_tracker(db, name) -> int:
    return db.execute(
        text(
            "INSERT INTO trackers (name, week_ending_weekday, first_week_ending, last_week_ending) "
            "VALUES (:n, 4, '2026-09-04', '2026-12-25') RETURNING id"
        ),
        {"n": name},
    ).scalar_one()


def test_upgrade_keeps_teams_and_trackers_unset_and_seeds_two_business_lines(db, at_revision_0003):
    team_id = db.execute(text("INSERT INTO teams (name) VALUES ('Desktop') RETURNING id")).scalar_one()
    tracker_id = _insert_tracker(db, "A")
    db.commit()
    command.upgrade(alembic_config(), "head")
    assert db.get(Team, team_id).location_id is None
    assert db.get(Tracker, tracker_id).business_line_id is None
    assert db.scalar(select(func.count()).select_from(TrackerRegion)) == 0
    assert sorted(db.scalars(select(BusinessLine.name))) == ["Tradition brokerage", "TraditionData"]
    assert db.scalar(select(func.count()).select_from(Region)) == 0
