"""The import template: built from the importer's layout, stored, served and checked for example values."""

from io import BytesIO

from openpyxl import load_workbook

from tests.conftest import post
from tests.importer.build_fixture import workbook_bytes
from tracker.importer import read_workbook
from tracker.importer.template import TEMPLATE_PATH, build_template, example_leftovers, write_template

FRIDAY = 4


def cells(workbook) -> dict:
    """Every sheet's non-empty cell values and data-validation lists, for comparing two workbooks."""
    found = {}
    for sheet in workbook.worksheets:
        values = {c.coordinate: c.value for row in sheet.iter_rows() for c in row if c.value is not None}
        lists = sorted((str(v.sqref), v.formula1) for v in sheet.data_validations.dataValidation)
        found[sheet.title] = (values, lists)
    return found


def saved(workbook) -> BytesIO:
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def test_the_stored_template_imports_as_it_stands():
    preview = read_workbook(TEMPLATE_PATH, FRIDAY)
    assert preview.mismatch == 0 and preview.group_total == 25
    assert [g["name"] for g in preview.groups] == ["London", "New York", "Geneva"]
    assert [r["ref"] for r in preview.risks] == ["R-03", "R-05", "R-07"]
    assert len(preview.weeks) == 40 and preview.inputs["status"] == "Green"


def test_the_stored_template_is_the_built_one():
    stored = load_workbook(TEMPLATE_PATH)
    built = load_workbook(saved(build_template()))
    assert stored.sheetnames == built.sheetnames
    assert stored.sheetnames[0] == "Instructions"
    assert cells(stored) == cells(built), "Run `flask build-import-template` and commit the file."


def test_the_command_writes_the_built_template(app, tmp_path):
    target = tmp_path / "template.xlsx"
    write_template(target)
    assert cells(load_workbook(target)) == cells(load_workbook(saved(build_template())))
    result = app.test_cli_runner().invoke(args=["build-import-template", "--path", str(target)])
    assert result.exit_code == 0 and str(target) in result.output


def test_the_template_offers_lists_for_rag_status_and_report_day():
    lists = {formula for _values, found in cells(build_template()).values() for _ref, formula in found}
    assert '"Green,Amber,Red"' in lists and '"Open,In progress,Closed"' in lists
    assert '"Monday,Tuesday,Wednesday,Thursday,Friday"' in lists


def test_example_values_left_in_are_named():
    leftovers = example_leftovers(read_workbook(TEMPLATE_PATH, FRIDAY))
    assert any("London" in item for item in leftovers) and any("R-07" in item for item in leftovers)
    assert any("update" in item for item in leftovers)
    assert example_leftovers(read_workbook(BytesIO(workbook_bytes()), FRIDAY)) == []


def test_the_download_needs_the_import_permission(client, logged_in_user):
    assert client.get("/import/template").status_code == 403


def test_the_import_page_links_the_template_and_guides(client, logged_in_admin):
    page = client.get("/import").get_data(as_text=True)
    assert 'href="/import/template"' in page and "What the workbook needs" in page
    response = client.get("/import/template")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment; filename=import-template.xlsx")
    assert load_workbook(BytesIO(response.data)).sheetnames[0] == "Instructions"


def test_the_preview_warns_about_example_values(client, logged_in_admin):
    with open(TEMPLATE_PATH, "rb") as handle:
        response = post(
            client,
            "/import",
            {"weekday": "4", "workbook": (BytesIO(handle.read()), "template.xlsx")},
            content_type="multipart/form-data",
        )
    page = response.get_data(as_text=True)
    assert response.status_code == 200 and "still holds the example" in page and "R-07" in page
