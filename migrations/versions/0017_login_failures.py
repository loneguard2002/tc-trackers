"""Sign-in failures: the sign-in limiter counts in the database, shared by every worker and instance.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('account', 'address')", name=op.f("ck_login_failures_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_failures")),
    )
    op.create_index("ix_login_failures_kind_value_at", "login_failures", ["kind", "value", "at"])
    op.create_index("ix_login_failures_at", "login_failures", ["at"])


def downgrade() -> None:
    op.drop_table("login_failures")
