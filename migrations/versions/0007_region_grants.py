"""Region grants give a person a role on every tracker covering a region.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "region_grants",
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'owner')", name=op.f("ck_region_grants_role")),
        sa.ForeignKeyConstraint(
            ["region_id"], ["regions.id"], name=op.f("fk_region_grants_region_id_regions"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_region_grants_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("region_id", "user_id", name=op.f("pk_region_grants")),
    )
    op.create_index("ix_region_grants_user_id", "region_grants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_region_grants_user_id", table_name="region_grants")
    op.drop_table("region_grants")
