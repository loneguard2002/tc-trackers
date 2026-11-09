"""Each tracker gets a person in charge, reminders before the automatic send are recorded, and saved email messages
that are the old default give way to the new default message.

The upgrade puts the one person given Owner directly on a tracker in charge when there is exactly one. A downgrade
drops the person in charge and the reminders; removed messages are not restored.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# The default message before 2026-11-09, compared with whitespace removed so line endings and padding do not matter.
OLD_DEFAULT_BODY = """\
<p><strong>{{tracker_name}}</strong>: week ending {{week_ending}}</p>
<p><strong>Status:</strong> {{status}} – {{verdict}}</p>
<p>Forecast completion {{forecast_date}} against a target of {{target_date}}.
{{percent_complete}} complete ({{completed}} of {{total_scope}}; {{remaining}} remaining).</p>
<p>{{headline}}</p>
<p><strong>Needed from you:</strong> {{decisions}}</p>
<p><a href="{{report_link}}">Open the live report</a> (sign-in required).</p>
"""


def upgrade() -> None:
    op.add_column("trackers", sa.Column("lead_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_trackers_lead_user_id_users"), "trackers", "users", ["lead_user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_trackers_lead_user_id", "trackers", ["lead_user_id"])
    op.execute(
        """
        UPDATE trackers SET lead_user_id = owners.user_id
        FROM (SELECT tracker_id, min(user_id) AS user_id FROM tracker_roles WHERE role = 'owner'
              GROUP BY tracker_id HAVING count(*) = 1) AS owners
        WHERE owners.tracker_id = trackers.id
        """
    )
    op.create_table(
        "report_reminders",
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_report_reminders_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tracker_id", "week_ending", name=op.f("pk_report_reminders")),
    )
    op.execute(
        sa.text("DELETE FROM email_templates WHERE regexp_replace(body_html, '\\s', '', 'g') = :old").bindparams(
            old="".join(OLD_DEFAULT_BODY.split())
        )
    )


def downgrade() -> None:
    op.drop_table("report_reminders")
    op.drop_index("ix_trackers_lead_user_id", table_name="trackers")
    op.drop_constraint(op.f("fk_trackers_lead_user_id_users"), "trackers", type_="foreignkey")
    op.drop_column("trackers", "lead_user_id")
