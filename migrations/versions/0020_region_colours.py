"""Region colours: each region's code shows in one of eight set colours; existing regions take them in order.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("regions", sa.Column("colour", sa.SmallInteger(), server_default=sa.text("1"), nullable=False))
    op.create_check_constraint(op.f("ck_regions_colour"), "regions", "colour BETWEEN 1 AND 8")
    op.execute(
        """
        UPDATE regions SET colour = ordered.colour
        FROM (SELECT id, (row_number() OVER (ORDER BY lower(code), id) - 1) % 8 + 1 AS colour FROM regions) AS ordered
        WHERE regions.id = ordered.id
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_regions_colour"), "regions", type_="check")
    op.drop_column("regions", "colour")
