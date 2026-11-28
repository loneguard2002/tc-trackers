from alembic import command
from conftest import alembic_config
from sqlalchemy import text


def test_sets_with_manage_teams_gain_create_teams_and_downgrade_takes_it_away(db):
    try:
        command.downgrade(alembic_config(), "0021")
        for name, permissions in (("Team leads", ["manage_teams", "view_activity"]), ("Auditors", ["view_activity"])):
            set_id = db.execute(
                text("INSERT INTO permission_sets (name) VALUES (:n) RETURNING id"), {"n": name}
            ).scalar()
            for permission in permissions:
                db.execute(
                    text("INSERT INTO permission_set_permissions (set_id, permission) VALUES (:s, :p)"),
                    {"s": set_id, "p": permission},
                )
        db.commit()
        command.upgrade(alembic_config(), "0022")
        held = "SELECT s.name FROM permission_sets s JOIN permission_set_permissions p ON p.set_id = s.id "
        query = text(held + "WHERE p.permission = 'create_teams'")
        assert db.execute(query).scalars().all() == ["Team leads"]
        db.commit()
        command.downgrade(alembic_config(), "0021")
        assert db.execute(query).scalars().all() == []
    finally:
        db.rollback()
        command.upgrade(alembic_config(), "head")
        db.execute(text("DELETE FROM permission_sets"))
        db.commit()
