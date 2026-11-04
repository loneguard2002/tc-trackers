"""Locations get a short code and an ISO country code in place of the typed country.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import context, op

from tracker.lists.countries import country_name, match_country

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("locations", sa.Column("code", sa.Text(), nullable=True))
    op.add_column("locations", sa.Column("country_code", sa.Text(), nullable=True))
    # An offline (SQL script) run cannot read rows, so it only emits the structure.
    rows = [] if context.is_offline_mode() else bind.execute(sa.text("SELECT id, city, country FROM locations")).all()
    converted = [(row.id, row.city, match_country(row.country)) for row in rows]
    seen: dict[tuple[str, str], str] = {}
    clashes: list[str] = []
    for _, city, country_code in converted:
        if country_code is None:
            continue
        key = (city.lower(), country_code)
        if key in seen:
            clashes.append(f"{seen[key]} and {city} ({country_name(country_code)})")
        else:
            seen[key] = city
    if clashes:
        raise RuntimeError("Locations that become the same place: " + "; ".join(clashes))
    for location_id, _, country_code in converted:
        bind.execute(
            sa.text("UPDATE locations SET country_code = :c WHERE id = :i"), {"c": country_code, "i": location_id}
        )
    op.drop_index("uq_locations_city_country_lower", table_name="locations")
    op.drop_column("locations", "country")
    op.create_index("uq_locations_code_lower", "locations", [sa.text("lower(code)")], unique=True)
    op.create_index(
        "uq_locations_city_country_code", "locations", [sa.text("lower(city)"), "country_code"], unique=True
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("uq_locations_city_country_code", table_name="locations")
    op.drop_index("uq_locations_code_lower", table_name="locations")
    op.add_column("locations", sa.Column("country", sa.Text(), nullable=True))
    rows = [] if context.is_offline_mode() else bind.execute(sa.text("SELECT id, country_code FROM locations")).all()
    for location_id, country_code in rows:
        bind.execute(
            sa.text("UPDATE locations SET country = :c WHERE id = :i"),
            {"c": country_name(country_code) or "", "i": location_id},
        )
    op.alter_column("locations", "country", nullable=False)
    op.drop_column("locations", "code")
    op.drop_column("locations", "country_code")
    op.create_index(
        "uq_locations_city_country_lower",
        "locations",
        [sa.text("lower(city)"), sa.text("lower(country)")],
        unique=True,
    )
