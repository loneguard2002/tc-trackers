"""Calendar reminders: who has asked for a weekly calendar reminder on a tracker, and what was last delivered.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_reminders",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_state", sa.Text(), server_default="none", nullable=False),
        sa.Column("sent_fingerprint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "sent_state IN ('none', 'sent', 'cancelled')", name=op.f("ck_calendar_reminders_sent_state")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_calendar_reminders_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_calendar_reminders_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "tracker_id", name=op.f("pk_calendar_reminders")),
    )
    op.create_index("ix_calendar_reminders_tracker_id", "calendar_reminders", ["tracker_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_reminders_tracker_id", table_name="calendar_reminders")
    op.drop_table("calendar_reminders")
