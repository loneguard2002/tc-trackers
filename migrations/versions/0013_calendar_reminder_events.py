"""Calendar reminder events: the history of switches, deliveries and downloads of each person's reminder.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_reminder_events",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint(
            "kind IN ('switched_on', 'switched_off', 'sent', 'updated', 'cancelled', 'failed', 'downloaded')",
            name=op.f("ck_calendar_reminder_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_calendar_reminder_events_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"],
            ["trackers.id"],
            name=op.f("fk_calendar_reminder_events_tracker_id_trackers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_reminder_events")),
    )
    op.create_index(
        "ix_calendar_reminder_events_user_id_tracker_id_at",
        "calendar_reminder_events",
        ["user_id", "tracker_id", "at"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_reminder_events_user_id_tracker_id_at", table_name="calendar_reminder_events")
    op.drop_table("calendar_reminder_events")
