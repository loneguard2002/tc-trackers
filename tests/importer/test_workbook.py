"""Workbook import: pure reading tests run without a database; creation tests need one."""

from datetime import date, datetime
from io import BytesIO

import pytest
from openpyxl.utils.datetime import to_excel
from sqlalchemy import select

from tests.conftest import post
from tests.importer.build_fixture import workbook_bytes
from tracker.engine.calc import GroupInput, build_headline, build_week_rows, group_positions
from tracker.importer import ImportError_, ImportMismatch, create_tracker_from_preview, read_workbook
from tracker.importer.workbook import ImportPreview, eval_simple_formula, to_date
from tracker.models import AuditLog, Group, ReportInput, Risk, Tracker, TrackerRole, Week
from tracker.report.build import compute_position


@pytest.fixture
def fixture_xlsx():
    return BytesIO(workbook_bytes())


@pytest.fixture
def fixture_xlsx_mismatch():
    return BytesIO(workbook_bytes(deployed_site_a=136))


def tweaked(tweak) -> BytesIO:
    return BytesIO(workbook_bytes(tweak=tweak))


# --- eval_simple_formula ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        (5, 5),
        (5.0, 5),
        ("=202+135", 337),
        ("= (2+3)*4 ", 20),
        ("=-3+10/5", -1),
        ("=1.5*2", 3),
    ],
)
def test_eval_accepts_simple_arithmetic(value, expected):
    assert eval_simple_formula(value, "Sheet!A1") == expected


@pytest.mark.parametrize(
    "value",
    [
        "=SUM(A1:A3)",
        "=__import__('os')",
        "=2**3",
        "=1/0",
        "=10/4",
        "=1.5",
        "=" + "1+" * 150 + "1",
        "337",
        "=A1+1",
        "=()",
        True,
        2.5,
        float("nan"),
        [1],
    ],
)
def test_eval_rejects_everything_else(value):
    with pytest.raises(ImportError_, match="Sheet!B7"):
        eval_simple_formula(value, "Sheet!B7")


# --- dates -----------------------------------------------------------------------------------------------------


def test_dates_accept_datetime_date_and_excel_serial():
    assert to_date(datetime(2026, 9, 7, 13, 30), "S!A1") == date(2026, 9, 7)
    assert to_date(date(2026, 9, 7), "S!A1") == date(2026, 9, 7)
    assert to_date(to_excel(datetime(2026, 9, 7)), "S!A1") == date(2026, 9, 7)
    assert to_date(None, "S!A1") is None


@pytest.mark.parametrize("value", ["next Monday", True, -5000000])
def test_dates_reject_other_values(value):
    with pytest.raises(ImportError_, match="S!A1"):
        to_date(value, "S!A1")


# --- read_workbook ---------------------------------------------------------------------------------------------


def test_import_evaluates_baseline_formula(fixture_xlsx):
    p = read_workbook(fixture_xlsx, weekday=4)
    assert p.groups[0]["baseline"] == 337
    assert [g["name"] for g in p.groups] == ["Site A", "Site B", "Remote"]
    assert p.groups[0]["starting_completed"] == 135
    assert p.groups[0]["ready_not_complete"] == 5
    assert p.groups[0]["rag"] == "Amber" and p.groups[0]["planned_completion"] == date(2026, 11, 20)


def test_import_maps_monday_rows_to_previous_friday(fixture_xlsx):
    p = read_workbook(fixture_xlsx, weekday=4)
    assert p.settings["first_week_ending"] == date(2026, 9, 4)
    assert p.settings["last_week_ending"] == date(2026, 9, 25)
    assert [w["week_ending"] for w in p.weeks] == [
        date(2026, 9, 4),
        date(2026, 9, 11),
        date(2026, 9, 18),
        date(2026, 9, 25),
    ]
    assert [w["actual"] for w in p.weeks] == [40, 38, 20, 40]
    assert [w["target"] for w in p.weeks] == [35, 40, 40, 40]
    assert p.inputs["week_ending"] == date(2026, 9, 25)
    assert p.inputs["status"] == "Green"
    assert [r["ref"] for r in p.risks] == ["R1"] and p.risks[0]["group"] == "Site A"


def test_import_snaps_a_midweek_first_report_date_back_to_the_report_day():
    def thursday(wb):
        wb["Settings"]["B6"] = datetime(2026, 9, 10)  # a Thursday; the workbook moves it back to Monday 7 September

    p = read_workbook(tweaked(thursday), weekday=4)
    assert p.settings["first_week_ending"] == date(2026, 9, 4)


def test_import_reconciles_when_figures_agree(fixture_xlsx):
    p = read_workbook(fixture_xlsx, weekday=4)
    assert (p.group_total, p.weekly_total, p.mismatch) == (138, 138, 0)


def test_import_reports_mismatch_in_preview(fixture_xlsx_mismatch):
    p = read_workbook(fixture_xlsx_mismatch, weekday=4)
    assert p.mismatch == 1


def test_import_caps_the_last_report_date_at_51_weeks_after_the_first():
    def far(wb):
        wb["Settings"]["B7"] = datetime(2030, 1, 7)

    p = read_workbook(tweaked(far), weekday=4)
    assert len(p.weeks) == 52 and p.settings["last_week_ending"] == date(2027, 8, 27)


def test_import_rejects_unsafe_formula():
    def unsafe(wb):
        wb["By Location"]["B6"] = "=SUM(A1:A3)"

    with pytest.raises(ImportError_, match="By Location!B6"):
        read_workbook(tweaked(unsafe), weekday=4)

    def worse(wb):
        wb["Weekly Tracker"]["C6"] = "=__import__('os')"

    with pytest.raises(ImportError_, match="Weekly Tracker!C6"):
        read_workbook(tweaked(worse), weekday=4)


def test_import_rejects_non_integral_formula():
    def fractional(wb):
        wb["By Location"]["B6"] = "=5/2"

    with pytest.raises(ImportError_, match="By Location!B6"):
        read_workbook(tweaked(fractional), weekday=4)


def test_import_rejects_bad_values_naming_the_cell():
    def bad_rag(wb):
        wb["By Location"]["H6"] = "Purple"

    def bad_date(wb):
        wb["Settings"]["B6"] = "tomorrow"

    def bad_ma(wb):
        wb["Settings"]["B10"] = 13

    def negative(wb):
        wb["By Location"]["C6"] = -1

    for tweak, cell in [(bad_rag, "H6"), (bad_date, "B6"), (bad_ma, "B10"), (negative, "C6")]:
        with pytest.raises(ImportError_, match=cell):
            read_workbook(tweaked(tweak), weekday=4)


def test_import_rejects_missing_sheet_and_garbage():
    def drop(wb):
        del wb["Risks & Issues"]

    with pytest.raises(ImportError_, match="Risks & Issues"):
        read_workbook(tweaked(drop), weekday=4)
    with pytest.raises(ImportError_, match="could not be read"):
        read_workbook(BytesIO(b"not a workbook"), weekday=4)
    with pytest.raises(ImportError_, match="week-ending day"):
        read_workbook(BytesIO(workbook_bytes()), weekday=9)


def test_import_stops_at_total_row_and_skips_blank_names():
    def extra(wb):
        wb["By Location"]["A9"] = "Hidden"  # below the Total row: never imported
        wb["By Location"]["B9"] = 99

    p = read_workbook(tweaked(extra), weekday=4)
    assert [g["name"] for g in p.groups] == ["Site A", "Site B", "Remote"]


def test_preview_survives_json_round_trip(fixture_xlsx):
    import json

    p = read_workbook(fixture_xlsx, weekday=4)
    again = ImportPreview.from_json(json.loads(json.dumps(p.to_json())))
    assert again == p
    with pytest.raises(ImportError_):
        ImportPreview.from_json({"settings": {}})


def test_preview_drives_the_engine_to_the_workbook_figures(fixture_xlsx):
    """Database-free check of the brief's engine figures: completed 138, scope 369, forecast week ending 25 Sep."""
    p = read_workbook(fixture_xlsx, weekday=4)
    s = p.settings
    weeks = [w["week_ending"] for w in p.weeks]
    rows = build_week_rows(
        weeks,
        {w["week_ending"]: w["target"] for w in p.weeks},
        {w["week_ending"]: w["actual"] for w in p.weeks},
        sum(g["baseline"] for g in p.groups),
        s["completed_before_first"],
        s["moving_average_weeks"],
        date(2026, 9, 25),
        4,
    )
    groups = [
        GroupInput(i, g["name"], g["baseline"], g["starting_completed"], g["ready_not_complete"], None, None, "", False)
        for i, g in enumerate(p.groups)
    ]
    headline = build_headline(
        rows, group_positions(groups, {}), s["completed_before_first"], s["target_completion"], date(2026, 9, 25)
    )
    assert headline.completed == 138 and headline.total_scope == 369
    assert headline.forecast_based_on == date(2026, 9, 25)
    assert headline.totals_check_ok


# --- Pages that do not need the database -------------------------------------------------------------------------


def test_import_page_requires_sign_in(client):
    assert client.get("/import").status_code == 302
    assert post(client, "/import/confirm", {"payload": "x"}).status_code == 302


# --- Database tests ----------------------------------------------------------------------------------------------


def test_import_creates_tracker(db, fixture_xlsx, user_factory):
    admin = user_factory(is_admin=True)
    p = read_workbook(fixture_xlsx, weekday=4)
    tracker = create_tracker_from_preview(db, p, "Rollout", "thin clients", "Location", admin.id, False)
    db.commit()
    stored = db.get(Tracker, tracker.id)
    assert stored.first_week_ending == date(2026, 9, 4) and stored.last_week_ending == date(2026, 9, 25)
    assert stored.moving_average_weeks == 3 and stored.target_completion == date(2026, 12, 18)
    groups = db.scalars(select(Group).where(Group.tracker_id == tracker.id).order_by(Group.sort_order)).all()
    assert [(g.name, g.baseline, g.starting_completed) for g in groups] == [
        ("Site A", 337, 135),
        ("Site B", 2, 0),
        ("Remote", 30, 3),
    ]
    weeks = db.scalars(select(Week).where(Week.tracker_id == tracker.id).order_by(Week.week_ending)).all()
    assert [w.imported_actual for w in weeks] == [40, 38, 20, 40] and [w.target for w in weeks][0] == 35
    risk = db.scalars(select(Risk).where(Risk.tracker_id == tracker.id)).one()
    assert risk.ref == "R1" and risk.group_id == groups[0].id and risk.status == "Open"
    inputs = db.get(ReportInput, (tracker.id, date(2026, 9, 25)))
    assert inputs.status == "Green" and inputs.prepared_by == admin.id
    assert db.get(TrackerRole, (admin.id, tracker.id)).role == "owner"
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "tracker_imported")).one()
    assert audit.tracker_id == tracker.id and audit.user_id == admin.id


def test_import_reports_mismatch(db, fixture_xlsx_mismatch, user_factory):
    admin = user_factory(is_admin=True)
    p = read_workbook(fixture_xlsx_mismatch, weekday=4)
    with pytest.raises(ImportMismatch) as caught:
        create_tracker_from_preview(db, p, "Rollout", "", "", admin.id, False)
    assert caught.value.mismatch == 1
    assert db.scalars(select(Tracker)).first() is None
    tracker = create_tracker_from_preview(db, p, "Rollout", "", "", admin.id, True)
    assert tracker.id is not None


def test_import_requires_a_name(db, fixture_xlsx, user_factory):
    admin = user_factory(is_admin=True)
    with pytest.raises(ImportError_, match="name"):
        create_tracker_from_preview(db, read_workbook(fixture_xlsx, 4), "  ", "", "", admin.id, False)


def test_imported_figures_match_engine(db, fixture_xlsx, user_factory):
    admin = user_factory(is_admin=True)
    tracker = create_tracker_from_preview(db, read_workbook(fixture_xlsx, 4), "Rollout", "", "", admin.id, False)
    db.commit()
    headline = compute_position(db, tracker, date(2026, 9, 25), date(2026, 10, 30)).headline
    assert headline.completed == 138 and headline.total_scope == 369
    assert headline.forecast_based_on == date(2026, 9, 25) and headline.totals_check_ok


def test_import_page_admin_only(client, logged_in_user):
    assert client.get("/import").status_code == 403
    assert post(client, "/import/confirm", {"payload": "x"}).status_code == 403


def _upload(client, data=None):
    return post(
        client,
        "/import",
        {"weekday": "4", "workbook": (BytesIO(data or workbook_bytes()), "book.xlsx")},
        content_type="multipart/form-data",
    )


def test_upload_shows_preview_then_confirm_creates_tracker(client, logged_in_admin, db):
    assert client.get("/import").status_code == 200
    response = _upload(client)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Site A" in html and "accept_mismatch" not in html
    token = html.split('name="payload" value="')[1].split('"')[0]
    done = post(client, "/import/confirm", {"payload": token, "name": "Rollout", "unit_label": "x", "group_label": "L"})
    assert done.status_code == 302
    assert db.scalars(select(Tracker).where(Tracker.name == "Rollout")).one() is not None


def test_confirm_with_mismatch_needs_acceptance(client, logged_in_admin, db):
    html = _upload(client, workbook_bytes(deployed_site_a=136)).get_data(as_text=True)
    assert "accept_mismatch" in html
    token = html.split('name="payload" value="')[1].split('"')[0]
    refused = post(client, "/import/confirm", {"payload": token, "name": "Rollout"})
    assert refused.status_code == 400
    assert db.scalars(select(Tracker)).first() is None
    accepted = post(client, "/import/confirm", {"payload": token, "name": "Rollout", "accept_mismatch": "1"})
    assert accepted.status_code == 302


def test_confirm_rejects_tampered_and_expired_payloads(client, logged_in_admin, app, monkeypatch):
    html = _upload(client).get_data(as_text=True)
    token = html.split('name="payload" value="')[1].split('"')[0]
    tampered = post(client, "/import/confirm", {"payload": token[:-3] + "xyz", "name": "Rollout"})
    assert tampered.status_code == 302 and tampered.headers["Location"].endswith("/import")
    import tracker.importer.views as views

    monkeypatch.setattr(views, "MAX_AGE_SECONDS", -1)
    expired = post(client, "/import/confirm", {"payload": token, "name": "Rollout"})
    assert expired.status_code == 302 and expired.headers["Location"].endswith("/import")


def test_upload_of_a_bad_file_shows_a_message(client, logged_in_admin):
    response = _upload(client, b"not a workbook")
    assert response.status_code == 400 and "could not be read" in response.get_data(as_text=True)
