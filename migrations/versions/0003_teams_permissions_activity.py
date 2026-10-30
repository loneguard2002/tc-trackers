"""Teams, permission sets, tracker teams and the affected user on activity entries.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), sa.Identity(), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "teams",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["teams.id"], name=op.f("fk_teams_parent_id_teams"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
    )
    op.create_index("uq_teams_name_lower", "teams", [sa.text("lower(name)")], unique=True)
    op.create_index("ix_teams_parent_id", "teams", ["parent_id"])

    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'owner')", name=op.f("ck_team_members_role")),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_members_team_id_teams"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_team_members_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_team_members")),
    )
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    op.create_table(
        "permission_sets",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permission_sets")),
    )
    op.create_index("uq_permission_sets_name_lower", "permission_sets", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "permission_set_permissions",
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["set_id"],
            ["permission_sets.id"],
            name=op.f("fk_permission_set_permissions_set_id_permission_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("set_id", "permission", name=op.f("pk_permission_set_permissions")),
    )

    op.create_table(
        "permission_set_holders",
        _id(),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("num_nonnulls(team_id, user_id) = 1", name=op.f("ck_permission_set_holders_one_holder")),
        sa.ForeignKeyConstraint(
            ["set_id"],
            ["permission_sets.id"],
            name=op.f("fk_permission_set_holders_set_id_permission_sets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_permission_set_holders_team_id_teams"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_permission_set_holders_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permission_set_holders")),
    )
    op.create_index(
        "uq_permission_set_holders_set_team",
        "permission_set_holders",
        ["set_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )
    op.create_index(
        "uq_permission_set_holders_set_user",
        "permission_set_holders",
        ["set_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    op.add_column("trackers", sa.Column("team_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_trackers_team_id_teams"), "trackers", "teams", ["team_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_trackers_team_id", "trackers", ["team_id"])

    op.add_column("audit_log", sa.Column("target_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_audit_log_target_user_id_users"),
        "audit_log",
        "users",
        ["target_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.create_index("ix_audit_log_target_user_id", "audit_log", ["target_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    # Compare as text so that an entity_id which is not a number cannot fail a cast.
    op.execute(
        "UPDATE audit_log SET target_user_id = users.id FROM users "
        "WHERE audit_log.entity = 'user' AND audit_log.entity_id = users.id::text"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_target_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_at", table_name="audit_log")
    op.drop_constraint(op.f("fk_audit_log_target_user_id_users"), "audit_log", type_="foreignkey")
    op.drop_column("audit_log", "target_user_id")

    op.drop_index("ix_trackers_team_id", table_name="trackers")
    op.drop_constraint(op.f("fk_trackers_team_id_teams"), "trackers", type_="foreignkey")
    op.drop_column("trackers", "team_id")

    op.drop_index("uq_permission_set_holders_set_user", table_name="permission_set_holders")
    op.drop_index("uq_permission_set_holders_set_team", table_name="permission_set_holders")
    op.drop_table("permission_set_holders")
    op.drop_table("permission_set_permissions")
    op.drop_index("uq_permission_sets_name_lower", table_name="permission_sets")
    op.drop_table("permission_sets")
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_parent_id", table_name="teams")
    op.drop_index("uq_teams_name_lower", table_name="teams")
    op.drop_table("teams")
