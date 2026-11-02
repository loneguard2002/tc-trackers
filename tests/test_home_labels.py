"""The home cards, list rows and filters, and the report header, show each tracker's business line and regions."""

import html
import re

from tracker.lists.catalogue import set_tracker_regions


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def test_cards_show_business_line_and_regions_and_carry_filter_data(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    line = business_line_factory()
    labelled = tracker_factory(name="Labelled", business_line_id=line.id)
    set_tracker_regions(db, labelled.id, [emea.id, apac.id])
    db.commit()
    tracker_factory(name="Bare")
    page = client.get("/").get_data(as_text=True)
    assert "Tradition brokerage · APAC, EMEA" in page
    assert "Business line not set · Regions not set" in page
    assert f'data-regions=" {apac.id} {emea.id} "' in page or f'data-regions=" {emea.id} {apac.id} "' in page
    assert 'data-regions=" none "' in page
    assert f'data-line="{line.id}"' in page
    assert 'data-line="none"' in page
    # Two cards and two list rows carry the filter data.
    assert page.count("data-regions=") == 4 and page.count("data-line=") == 4


def test_card_subtitle_puts_the_team_first(
    client, logged_in_admin, db, tracker_factory, team_factory, region_factory, business_line_factory
):
    team = team_factory(name="Desktop")
    region = region_factory("EMEA")
    tracker = tracker_factory(name="Teamed", team_id=team.id, business_line_id=business_line_factory().id)
    set_tracker_regions(db, tracker.id, [region.id])
    db.commit()
    page = text_of(client.get("/"))
    assert '<p class="tracker-card-team">Desktop · Tradition brokerage · EMEA</p>' in page
    # The list view's tracker cell shows the same line.
    assert '<span class="cell-sub">Desktop · Tradition brokerage · EMEA</span>' in page


def test_home_filter_selects_offer_the_lines_and_regions_in_use(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    emea, apac = region_factory("emea"), region_factory("APAC")
    region_factory("Unused")
    brokerage, data = business_line_factory("tradition brokerage"), business_line_factory("Data")
    business_line_factory("Unused line")
    one = tracker_factory(name="One", business_line_id=brokerage.id)
    two = tracker_factory(name="Two", business_line_id=data.id)
    set_tracker_regions(db, one.id, [emea.id])
    set_tracker_regions(db, two.id, [apac.id, emea.id])
    db.commit()
    page = text_of(client.get("/"))

    line_select = re.search(r"<select[^>]*data-home-line[^>]*>(.*?)</select>", page, re.S)
    region_select = re.search(r"<select[^>]*data-home-region[^>]*>(.*?)</select>", page, re.S)
    assert line_select and region_select
    line_options = re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', line_select.group(1))
    region_options = re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', region_select.group(1))
    assert line_options == [("all", "All"), (str(data.id), "Data"), (str(brokerage.id), "tradition brokerage")]
    assert region_options == [("all", "All"), (str(apac.id), "APAC"), (str(emea.id), "emea")]
    assert ">Business line</label>" in page and ">Region</label>" in page


def test_home_filter_selects_offer_not_set_last_when_a_card_lacks_it(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    emea = region_factory("EMEA")
    line = business_line_factory()
    labelled = tracker_factory(name="Labelled", business_line_id=line.id)
    set_tracker_regions(db, labelled.id, [emea.id])
    db.commit()
    tracker_factory(name="Bare")
    page = text_of(client.get("/"))
    line_select = re.search(r"<select[^>]*data-home-line[^>]*>(.*?)</select>", page, re.S).group(1)
    region_select = re.search(r"<select[^>]*data-home-region[^>]*>(.*?)</select>", page, re.S).group(1)
    assert re.findall(r'<option value="([^"]+)"', line_select) == ["all", str(line.id), "none"]
    assert re.findall(r'<option value="([^"]+)"', region_select) == ["all", str(emea.id), "none"]
    assert ">Not set</option>" in line_select


def test_report_header_shows_business_line_and_regions(
    client, logged_in_admin, db, tracker_factory, region_factory, business_line_factory
):
    region = region_factory("EMEA")
    tracker = tracker_factory(name="Reported", business_line_id=business_line_factory().id)
    set_tracker_regions(db, tracker.id, [region.id])
    db.commit()
    page = text_of(client.get(f"/trackers/{tracker.id}/report"))
    assert '<p class="report-meta">Tradition brokerage · EMEA</p>' in page


def test_report_header_says_when_business_line_and_regions_are_not_set(client, logged_in_admin, tracker_factory):
    tracker = tracker_factory(name="Bare report")
    page = text_of(client.get(f"/trackers/{tracker.id}/report"))
    assert '<p class="report-meta">Business line not set · Regions not set</p>' in page


def test_report_labels_are_filled_by_build_report(db, tracker_factory, region_factory, business_line_factory):
    from datetime import date

    from tracker.report.build import build_report

    emea, apac = region_factory("EMEA"), region_factory("APAC")
    tracker = tracker_factory(business_line_id=business_line_factory().id)
    set_tracker_regions(db, tracker.id, [emea.id, apac.id])
    db.commit()
    report = build_report(db, tracker, None, date(2026, 10, 1))
    assert report.labels.business_line == "Tradition brokerage"
    assert report.labels.regions == ["APAC", "EMEA"]
