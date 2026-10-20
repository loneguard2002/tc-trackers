"""Initial schema.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")
FALSE = sa.text("false")


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), sa.Identity(), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def _text(name: str, default: str = "") -> sa.Column:
    return sa.Column(name, sa.Text(), server_default=default, nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        _text("auth_source", "local"),
        _text("status", "pending"),
        sa.Column("is_admin", sa.Boolean(), server_default=FALSE, nullable=False),
        _created_at(),
        sa.CheckConstraint("auth_source IN ('local', 'sso')", name=op.f("ck_users_auth_source")),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled')", name=op.f("ck_users_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "trackers",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        _text("unit_label"),
        _text("group_label"),
        _text("description"),
        _text("status", "active"),
        sa.Column("week_ending_weekday", sa.SmallInteger(), nullable=False),
        sa.Column("first_week_ending", sa.Date(), nullable=False),
        sa.Column("last_week_ending", sa.Date(), nullable=False),
        sa.Column("target_completion", sa.Date(), nullable=True),
        sa.Column("completed_before_first", sa.Integer(), server_default="0", nullable=False),
        sa.Column("moving_average_weeks", sa.Integer(), server_default="3", nullable=False),
        sa.Column("send_time", sa.Time(), server_default=sa.text("'17:00'"), nullable=False),
        _text("send_timezone", "Europe/London"),
        sa.Column("schedule_enabled", sa.Boolean(), server_default=FALSE, nullable=False),
        _created_at(),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_trackers_status")),
        sa.CheckConstraint("week_ending_weekday BETWEEN 0 AND 6", name=op.f("ck_trackers_weekday")),
        sa.CheckConstraint("last_week_ending >= first_week_ending", name=op.f("ck_trackers_span_order")),
        sa.CheckConstraint("last_week_ending - first_week_ending <= 357", name=op.f("ck_trackers_span_52_weeks")),
        sa.CheckConstraint("moving_average_weeks BETWEEN 1 AND 12", name=op.f("ck_trackers_moving_average_weeks")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trackers")),
    )
    op.create_table(
        "tracker_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'owner')", name=op.f("ck_tracker_roles_role")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tracker_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_tracker_roles_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "tracker_id", name=op.f("pk_tracker_roles")),
    )
    op.create_table(
        "audit_log",
        _id(),
        sa.Column("at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("tracker_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_audit_log_tracker_id_trackers"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_table(
        "groups",
        _id(),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("baseline", sa.Integer(), nullable=False),
        sa.Column("starting_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ready_not_complete", sa.Integer(), server_default="0", nullable=False),
        sa.Column("planned_completion", sa.Date(), nullable=True),
        sa.Column("rag", sa.Text(), nullable=True),
        _text("comment"),
        sa.Column("retired", sa.Boolean(), server_default=FALSE, nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("baseline >= 0", name=op.f("ck_groups_baseline")),
        sa.CheckConstraint("starting_completed >= 0", name=op.f("ck_groups_starting_completed")),
        sa.CheckConstraint("ready_not_complete >= 0", name=op.f("ck_groups_ready_not_complete")),
        sa.CheckConstraint("rag IN ('Green', 'Amber', 'Red')", name=op.f("ck_groups_rag")),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_groups_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("tracker_id", "name", name=op.f("uq_groups_tracker_id_name")),
    )
    op.create_table(
        "completion_entries",
        _id(),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        _text("note"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        _created_at(),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_completion_entries_quantity")),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_completion_entries_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_completion_entries_group_id_groups")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_completion_entries_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completion_entries")),
    )
    op.create_index(
        op.f("ix_completion_entries_tracker_week"), "completion_entries", ["tracker_id", "week_ending"], unique=False
    )
    op.create_table(
        "weeks",
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("target", sa.Integer(), nullable=True),
        sa.Column("imported_actual", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_weeks_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tracker_id", "week_ending", name=op.f("pk_weeks")),
    )
    op.create_table(
        "report_inputs",
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        _text("headline"),
        _text("decisions"),
        sa.Column("prepared_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("status IN ('Green', 'Amber', 'Red')", name=op.f("ck_report_inputs_status")),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_report_inputs_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prepared_by"], ["users.id"], name=op.f("fk_report_inputs_prepared_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("tracker_id", "week_ending", name=op.f("pk_report_inputs")),
    )
    op.create_table(
        "risks",
        _id(),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        _text("description"),
        _text("impact"),
        sa.Column("group_id", sa.Integer(), nullable=True),
        _text("owner_role"),
        sa.Column("raised_on", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        _text("status", "Open"),
        sa.Column("rag", sa.Text(), nullable=True),
        _text("latest_update"),
        sa.CheckConstraint("status IN ('Open', 'In progress', 'Closed')", name=op.f("ck_risks_status")),
        sa.CheckConstraint("rag IN ('Green', 'Amber', 'Red')", name=op.f("ck_risks_rag")),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_risks_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_risks_group_id_groups"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risks")),
        sa.UniqueConstraint("tracker_id", "ref", name=op.f("uq_risks_tracker_id_ref")),
    )
    op.create_table(
        "recipients",
        _id(),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        _text("name"),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_recipients_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipients")),
        sa.UniqueConstraint("tracker_id", "email", name=op.f("uq_recipients_tracker_id_email")),
    )
    op.create_table(
        "email_templates",
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_email_templates_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tracker_id", name=op.f("pk_email_templates")),
    )
    op.create_table(
        "report_sends",
        _id(),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        _created_at(),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trigger IN ('scheduled', 'manual')", name=op.f("ck_report_sends_trigger")),
        sa.CheckConstraint("status IN ('sending', 'sent', 'queued', 'failed')", name=op.f("ck_report_sends_status")),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_report_sends_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_report_sends_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_sends")),
    )
    op.create_index(
        "uq_report_sends_scheduled_week",
        "report_sends",
        ["tracker_id", "week_ending"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled'"),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )


def downgrade() -> None:
    for table in (
        "app_settings",
        "report_sends",
        "email_templates",
        "recipients",
        "risks",
        "report_inputs",
        "weeks",
        "completion_entries",
        "groups",
        "audit_log",
        "tracker_roles",
        "trackers",
        "users",
    ):
        op.drop_table(table)
