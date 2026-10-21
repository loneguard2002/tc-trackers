"""Add users.sso_subject (Entra tenant and object id) for SSO account matching.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sso_subject", sa.Text(), nullable=True))
    op.create_unique_constraint(op.f("uq_users_sso_subject"), "users", ["sso_subject"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_sso_subject"), "users", type_="unique")
    op.drop_column("users", "sso_subject")
