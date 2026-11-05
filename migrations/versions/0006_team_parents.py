"""Teams link to zero or more higher teams through team_parents, in place of the single teams.parent_id.

The upgrade makes each team's higher team its only link. A downgrade keeps only the lowest-id higher team of each team
and drops the others.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_parents",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("team_id <> parent_id", name=op.f("ck_team_parents_not_self")),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_parents_team_id_teams"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["teams.id"], name=op.f("fk_team_parents_parent_id_teams"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("team_id", "parent_id", name=op.f("pk_team_parents")),
    )
    op.create_index("ix_team_parents_parent_id", "team_parents", ["parent_id"])
    op.execute(
        "INSERT INTO team_parents (team_id, parent_id) SELECT id, parent_id FROM teams WHERE parent_id IS NOT NULL"
    )
    op.drop_index("ix_teams_parent_id", table_name="teams")
    op.drop_column("teams", "parent_id")


def downgrade() -> None:
    op.add_column("teams", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_teams_parent_id_teams"), "teams", "teams", ["parent_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_teams_parent_id", "teams", ["parent_id"])
    op.execute("UPDATE teams SET parent_id = (SELECT min(parent_id) FROM team_parents WHERE team_id = teams.id)")
    op.drop_index("ix_team_parents_parent_id", table_name="team_parents")
    op.drop_table("team_parents")
