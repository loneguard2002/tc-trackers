"""Feedback: requests, their conversation and their files.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_requests",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.Text(), server_default="new", nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=True),
        sa.Column("page_title", sa.Text(), server_default="", nullable=False),
        sa.Column("page_url", sa.Text(), server_default="", nullable=False),
        sa.Column("browser", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sender_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_note", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint("kind IN ('idea', 'problem')", name=op.f("ck_feedback_requests_kind")),
        sa.CheckConstraint(
            "status IN ('new', 'under_review', 'waiting', 'planned', 'done', 'will_not_do', 'withdrawn')",
            name=op.f("ck_feedback_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name=op.f("fk_feedback_requests_sender_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_requests")),
    )
    op.create_index("ix_feedback_requests_status_last_activity_at", "feedback_requests", ["status", "last_activity_at"])
    op.create_index("ix_feedback_requests_sender_id", "feedback_requests", ["sender_id"])

    op.create_table(
        "feedback_messages",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("status_from", sa.Text(), nullable=True),
        sa.Column("status_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('sender', 'reviewer', 'system')", name=op.f("ck_feedback_messages_role")),
        sa.CheckConstraint(
            "kind IN ('message', 'update', 'question', 'status', 'email')", name=op.f("ck_feedback_messages_kind")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["feedback_requests.id"],
            name=op.f("fk_feedback_messages_request_id_feedback_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_feedback_messages_author_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_messages")),
    )
    op.create_index("ix_feedback_messages_request_id_id", "feedback_messages", ["request_id", "id"])

    op.create_table(
        "feedback_files",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["feedback_requests.id"],
            name=op.f("fk_feedback_files_request_id_feedback_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["feedback_messages.id"],
            name=op.f("fk_feedback_files_message_id_feedback_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_files")),
    )


def downgrade() -> None:
    op.drop_table("feedback_files")
    op.drop_index("ix_feedback_messages_request_id_id", table_name="feedback_messages")
    op.drop_table("feedback_messages")
    op.drop_index("ix_feedback_requests_sender_id", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_status_last_activity_at", table_name="feedback_requests")
    op.drop_table("feedback_requests")
