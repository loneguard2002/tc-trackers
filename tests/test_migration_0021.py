import pytest
from alembic import command
from conftest import alembic_config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_existing_links_mark_the_first_by_name_as_main_and_downgrade_drops_it(db):
    try:
        command.downgrade(alembic_config(), "0020")
        ids = {}
        for name in ("Zed", "alpha", "Mid"):
            ids[name] = db.execute(text("INSERT INTO teams (name) VALUES (:n) RETURNING id"), {"n": name}).scalar()
        for parent in ("Zed", "alpha"):
            db.execute(
                text("INSERT INTO team_parents (team_id, parent_id) VALUES (:t, :p)"),
                {"t": ids["Mid"], "p": ids[parent]},
            )
        db.commit()
        command.upgrade(alembic_config(), "0021")
        mains = (
            db.execute(text("SELECT parent_id FROM team_parents WHERE team_id = :t AND is_main"), {"t": ids["Mid"]})
            .scalars()
            .all()
        )
        assert mains == [ids["alpha"]]  # by name ignoring case: alpha before Zed
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE team_parents SET is_main = true WHERE team_id = :t"), {"t": ids["Mid"]})
        db.rollback()
        command.downgrade(alembic_config(), "0020")
        columns = "SELECT column_name FROM information_schema.columns WHERE table_name = 'team_parents'"
        assert "is_main" not in db.execute(text(columns)).scalars().all()
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
        db.execute(text("DELETE FROM team_parents"))
        db.execute(text("DELETE FROM teams"))
        db.commit()
