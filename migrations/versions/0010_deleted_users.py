"""A person can be deleted: the status 'deleted' joins the others, and a deleted person no longer holds their email.

The unique email becomes a unique index over the people who are not deleted, so a deleted person's row keeps its
email for the history while a new account may use it. A downgrade turns each deleted person into a disabled one whose
email carries a suffix with the row's id, so the unique constraint can return.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_status"), "users", "status IN ('pending', 'active', 'disabled', 'deleted')"
    )
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.create_index("uq_users_email", "users", ["email"], unique=True, postgresql_where=sa.text("status <> 'deleted'"))


def downgrade() -> None:
    op.execute("UPDATE users SET status = 'disabled', email = email || '#deleted-' || id WHERE status = 'deleted'")
    op.drop_index("uq_users_email", table_name="users")
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_status"), "users", "status IN ('pending', 'active', 'disabled')")
