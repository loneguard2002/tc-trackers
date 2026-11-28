"""Create teams becomes its own permission (the owner, 28 Nov 2026). Every permission set holding Manage teams gains
it, so no one loses the ability to create teams today; an administrator can then take it out where it should go.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permission_set_permissions (set_id, permission)
        SELECT set_id, 'create_teams' FROM permission_set_permissions WHERE permission = 'manage_teams'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM permission_set_permissions WHERE permission = 'create_teams'")
