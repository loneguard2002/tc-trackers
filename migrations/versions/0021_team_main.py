"""The main higher team: one of a team's higher teams is its main, where the Teams screens show it; existing teams take
the first of their higher teams by name, as the screens showed them until now.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("team_parents", sa.Column("is_main", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute(
        """
        UPDATE team_parents SET is_main = true
        FROM (
            SELECT DISTINCT ON (tp.team_id) tp.team_id, tp.parent_id
            FROM team_parents tp JOIN teams t ON t.id = tp.parent_id
            ORDER BY tp.team_id, lower(t.name), t.id
        ) AS first
        WHERE team_parents.team_id = first.team_id AND team_parents.parent_id = first.parent_id
        """
    )
    op.create_index(
        "uq_team_parents_main", "team_parents", ["team_id"], unique=True, postgresql_where=sa.text("is_main")
    )


def downgrade() -> None:
    op.drop_index("uq_team_parents_main", table_name="team_parents")
    op.drop_column("team_parents", "is_main")
