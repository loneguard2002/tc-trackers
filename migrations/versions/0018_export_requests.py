"""Export requests: the per-person limit on PDF and PNG report downloads counts in the database.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_requests",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_export_requests_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_requests")),
    )
    op.create_index("ix_export_requests_user_id_at", "export_requests", ["user_id", "at"])
    op.create_index("ix_export_requests_at", "export_requests", ["at"])


def downgrade() -> None:
    op.drop_table("export_requests")
