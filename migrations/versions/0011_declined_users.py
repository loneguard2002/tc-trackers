"""An access request can be turned down: the status 'declined' joins the others.

A turned-down person keeps their Microsoft link, so signing in again shows that the request was not approved instead of
making a new request. A downgrade turns each declined person into a disabled one.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_status"), "users", "status IN ('pending', 'active', 'disabled', 'deleted', 'declined')"
    )


def downgrade() -> None:
    op.execute("UPDATE users SET status = 'disabled' WHERE status = 'declined'")
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_status"), "users", "status IN ('pending', 'active', 'disabled', 'deleted')"
    )
