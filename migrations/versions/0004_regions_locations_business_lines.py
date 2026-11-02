"""Regions, locations, business lines, tracker regions and the team location and tracker business line.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), sa.Identity(), nullable=False)


def _retired() -> sa.Column:
    return sa.Column("retired", sa.Boolean(), server_default=sa.text("false"), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "regions",
        _id(),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _retired(),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regions")),
    )
    op.create_index("uq_regions_code_lower", "regions", [sa.text("lower(code)")], unique=True)
    op.create_index("uq_regions_name_lower", "regions", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "locations",
        _id(),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        _retired(),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["region_id"], ["regions.id"], name=op.f("fk_locations_region_id_regions"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
    )
    op.create_index(
        "uq_locations_city_country_lower",
        "locations",
        [sa.text("lower(city)"), sa.text("lower(country)")],
        unique=True,
    )
    op.create_index("ix_locations_region_id", "locations", ["region_id"])

    business_lines = op.create_table(
        "business_lines",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        _retired(),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_lines")),
    )
    op.create_index("uq_business_lines_name_lower", "business_lines", [sa.text("lower(name)")], unique=True)
    op.bulk_insert(business_lines, [{"name": "Tradition brokerage"}, {"name": "TraditionData"}])

    op.create_table(
        "tracker_regions",
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracker_id"], ["trackers.id"], name=op.f("fk_tracker_regions_tracker_id_trackers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["regions.id"], name=op.f("fk_tracker_regions_region_id_regions"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tracker_id", "region_id", name=op.f("pk_tracker_regions")),
    )
    op.create_index("ix_tracker_regions_region_id", "tracker_regions", ["region_id"])

    op.add_column("teams", sa.Column("location_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_teams_location_id_locations"), "teams", "locations", ["location_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_teams_location_id", "teams", ["location_id"])

    op.add_column("trackers", sa.Column("business_line_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_trackers_business_line_id_business_lines"),
        "trackers",
        "business_lines",
        ["business_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_trackers_business_line_id", "trackers", ["business_line_id"])


def downgrade() -> None:
    op.drop_index("ix_trackers_business_line_id", table_name="trackers")
    op.drop_constraint(op.f("fk_trackers_business_line_id_business_lines"), "trackers", type_="foreignkey")
    op.drop_column("trackers", "business_line_id")

    op.drop_index("ix_teams_location_id", table_name="teams")
    op.drop_constraint(op.f("fk_teams_location_id_locations"), "teams", type_="foreignkey")
    op.drop_column("teams", "location_id")

    op.drop_index("ix_tracker_regions_region_id", table_name="tracker_regions")
    op.drop_table("tracker_regions")
    op.drop_index("uq_business_lines_name_lower", table_name="business_lines")
    op.drop_table("business_lines")
    op.drop_index("ix_locations_region_id", table_name="locations")
    op.drop_index("uq_locations_city_country_lower", table_name="locations")
    op.drop_table("locations")
    op.drop_index("uq_regions_name_lower", table_name="regions")
    op.drop_index("uq_regions_code_lower", table_name="regions")
    op.drop_table("regions")
