"""Week notes: a short note on each week's target, such as why it is lower or higher.

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
    op.add_column("weeks", sa.Column("note", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("weeks", "note")
