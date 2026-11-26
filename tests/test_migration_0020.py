from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def test_existing_regions_take_the_colours_in_code_order_and_downgrade_drops_them(db):
    try:
        command.downgrade(alembic_config(), "0019")
        codes = ["emea", "APAC", "Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7"]
        for code in codes:
            db.execute(text("INSERT INTO regions (code, name) VALUES (:code, :code)"), {"code": code})
        db.commit()
        command.upgrade(alembic_config(), "0020")
        colours = dict(db.execute(text("SELECT code, colour FROM regions")).all())
        # By code, ignoring case: APAC, emea, Z1 ... Z7; the ninth starts the colours again.
        assert colours == {"APAC": 1, "emea": 2, "Z1": 3, "Z2": 4, "Z3": 5, "Z4": 6, "Z5": 7, "Z6": 8, "Z7": 1}
        db.commit()
        command.downgrade(alembic_config(), "0019")
        columns = "SELECT column_name FROM information_schema.columns WHERE table_name = 'regions'"
        assert "colour" not in db.execute(text(columns)).scalars().all()
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
        db.execute(text("DELETE FROM regions"))
        db.commit()
