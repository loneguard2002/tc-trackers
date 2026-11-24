"""Target changes: the history of each tracker's target completion date.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "target_changes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("old_date", sa.Date(), nullable=True),
        sa.Column("new_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_target_changes_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"], ["users.id"], name=op.f("fk_target_changes_changed_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_target_changes")),
    )
    op.create_index("ix_target_changes_tracker_id_id", "target_changes", ["tracker_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_target_changes_tracker_id_id", table_name="target_changes")
    op.drop_table("target_changes")
