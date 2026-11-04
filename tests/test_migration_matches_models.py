"""Database-free check that the hand-written migration matches the models."""

import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config

from tracker.models import Base

ROOT = Path(__file__).resolve().parent.parent


def _offline_sql() -> str:
    buffer = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://localhost/offline")
    command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def _parse_tables(sql: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\)", sql, flags=re.S):
        columns = set()
        for line in body.splitlines():
            match = re.match(r"\s*(\w+)\s", line)
            if match and match.group(1).upper() not in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
                columns.add(match.group(1))
        tables[name] = columns
    for name, column in re.findall(r"ALTER TABLE (\w+) ADD COLUMN (\w+)", sql):
        tables[name].add(column)
    for name, column in re.findall(r"ALTER TABLE (\w+) DROP COLUMN (\w+)", sql):
        tables[name].discard(column)
    return tables


def test_migration_tables_and_columns_match_models():
    migrated = _parse_tables(_offline_sql())
    migrated.pop("alembic_version")
    expected = {table.name: {column.name for column in table.columns} for table in Base.metadata.sorted_tables}
    assert migrated == expected


def test_migration_creates_partial_unique_index_and_named_constraints():
    sql = _offline_sql()
    assert re.search(
        r"CREATE UNIQUE INDEX uq_report_sends_scheduled_week ON report_sends \(tracker_id, week_ending\) "
        r"WHERE trigger = 'scheduled'",
        sql,
    )
    named = {c.name for t in Base.metadata.tables.values() for c in t.constraints if c.name}
    missing = [name for name in named if name not in sql]
    assert not missing


def test_migration_creates_access_indexes_and_backfill():
    sql = _offline_sql()
    assert "CREATE UNIQUE INDEX uq_teams_name_lower ON teams (lower(name))" in sql
    assert "CREATE UNIQUE INDEX uq_permission_sets_name_lower ON permission_sets (lower(name))" in sql
    assert re.search(
        r"CREATE UNIQUE INDEX uq_permission_set_holders_set_team ON permission_set_holders "
        r"\(set_id, team_id\) WHERE team_id IS NOT NULL",
        sql,
    )
    assert re.search(
        r"CREATE UNIQUE INDEX uq_permission_set_holders_set_user ON permission_set_holders "
        r"\(set_id, user_id\) WHERE user_id IS NOT NULL",
        sql,
    )
    for name in ("ix_audit_log_at", "ix_audit_log_target_user_id", "ix_audit_log_action"):
        assert f"CREATE INDEX {name} ON audit_log" in sql
    assert re.search(
        r"UPDATE audit_log SET target_user_id = users\.id FROM users\s+WHERE audit_log\.entity = 'user' "
        r"AND audit_log\.entity_id = users\.id::text",
        sql,
    )


def test_migration_creates_list_indexes_and_seeds_business_lines():
    sql = _offline_sql()
    assert "CREATE UNIQUE INDEX uq_regions_code_lower ON regions (lower(code))" in sql
    assert "CREATE UNIQUE INDEX uq_regions_name_lower ON regions (lower(name))" in sql
    assert "CREATE UNIQUE INDEX uq_locations_code_lower ON locations (lower(code))" in sql
    assert "CREATE UNIQUE INDEX uq_locations_city_country_code ON locations (lower(city), country_code)" in sql
    assert "DROP INDEX uq_locations_city_country_lower" in sql
    assert "CREATE UNIQUE INDEX uq_business_lines_name_lower ON business_lines (lower(name))" in sql
    assert "'Tradition brokerage'" in sql and "'TraditionData'" in sql
