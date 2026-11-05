import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text


@pytest.fixture
def at_revision_0005(db):
    command.downgrade(alembic_config(), "0005")
    try:
        yield
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")


def _team(db, name, parent_id=None) -> int:
    return db.execute(
        text("INSERT INTO teams (name, parent_id) VALUES (:n, :p) RETURNING id"), {"n": name, "p": parent_id}
    ).scalar_one()


def test_upgrade_turns_each_parent_into_the_only_higher_team(db, at_revision_0005):
    a = _team(db, "A")
    b = _team(db, "B", a)
    _team(db, "C")
    db.commit()
    command.upgrade(alembic_config(), "head")
    assert set(db.execute(text("SELECT team_id, parent_id FROM team_parents")).all()) == {(b, a)}
    db.rollback()


def test_downgrade_keeps_the_lowest_id_higher_team(db, team_factory):
    first, second = team_factory("First"), team_factory("Second")
    both = team_factory("Both", parents=(second, first))
    top = team_factory("Top")
    try:
        command.downgrade(alembic_config(), "0005")
        got = dict(db.execute(text("SELECT id, parent_id FROM teams")).all())
        assert got == {first.id: None, second.id: None, both.id: first.id, top.id: None}
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
