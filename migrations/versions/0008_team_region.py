"""Teams store their region; the location becomes optional and, when set, lies in the team's region.

The upgrade gives each team with a location the region of that location. A downgrade drops the region, so a team with
a region and no location loses its place.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("region_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_teams_region_id_regions"), "teams", "regions", ["region_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_teams_region_id", "teams", ["region_id"])
    op.execute("UPDATE teams SET region_id = locations.region_id FROM locations WHERE locations.id = teams.location_id")
    op.create_unique_constraint(op.f("uq_locations_id_region_id"), "locations", ["id", "region_id"])
    op.create_foreign_key(
        op.f("fk_teams_location_id_region_id_locations"),
        "teams",
        "locations",
        ["location_id", "region_id"],
        ["id", "region_id"],
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_teams_location_has_region"), "teams", "location_id IS NULL OR region_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_teams_location_has_region"), "teams", type_="check")
    op.drop_constraint(op.f("fk_teams_location_id_region_id_locations"), "teams", type_="foreignkey")
    op.drop_constraint(op.f("uq_locations_id_region_id"), "locations", type_="unique")
    op.drop_index("ix_teams_region_id", table_name="teams")
    op.drop_constraint(op.f("fk_teams_region_id_regions"), "teams", type_="foreignkey")
    op.drop_column("teams", "region_id")
