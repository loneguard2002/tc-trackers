"""The home page: which trackers show, what each card says and the filter choices (database required).

The tests are grouped by area: A access and visibility, B card labels, C filter options, E progress and dates,
F status and alerts, G risks, H role, actions and person in charge. Area D, filtering in a real browser, is in
test_home_browser.py.
"""

import dataclasses
import html
import re
from datetime import date

import pytest

from tests.conftest import post
from tests.test_trackers import add_entry, make_group
from tracker.lists.catalogue import set_tracker_regions
from tracker.models import ReportInput, Risk
from tracker.report import build


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def cards_by_name(page: str) -> dict[str, str]:
    """Each home card's HTML, by tracker name, in page order."""
    cards = re.findall(r'<article class="tracker-card.*?</article>', page, re.S)
    return {re.search(r'<a href="[^"]*">([^<]*)</a>', card).group(1): card for card in cards}


# --- A. Access and visibility ---------------------------------------------------------------------------------------


def test_home_lists_only_visible_trackers(client, logged_in_user, tracker_factory, grant):
    mine = tracker_factory(name="Mine tracker")
    tracker_factory(name="Other tracker")
    grant(logged_in_user, mine, "viewer")
    page = client.get("/")
    assert b"Mine tracker" in page.data
    assert b"Other tracker" not in page.data


def test_archived_tracker_hidden_from_home_but_reachable(client, logged_in_admin, db, tracker_factory):
    tracker = tracker_factory(name="Old tracker")
    assert post(client, f"/trackers/{tracker.id}/archive").status_code == 302
    db.refresh(tracker)
    assert tracker.status == "archived"
    assert b"Old tracker" not in client.get("/").data
    assert b"Old tracker" in client.get("/?archived=1").data
    assert client.get(f"/trackers/{tracker.id}/groups").status_code == 200
    assert client.get(f"/trackers/{tracker.id}/settings").status_code == 200


def test_home_lists_team_trackers_with_their_role(client, logged_in_user, tracker_factory, team_factory, add_member):
    parent = team_factory(name="Infrastructure")
    windows, network = team_factory(name="Windows", parent=parent), team_factory(name="Network", parent=parent)
    add_member(parent, logged_in_user, "editor")
    tracker_factory(name="Patching tracker", team_id=windows.id)
    tracker_factory(name="Firewall tracker", team_id=network.id)
    tracker_factory(name="Unrelated tracker")
    page = client.get("/")
    assert b"Patching tracker" in page.data and b"Firewall tracker" in page.data
    assert b"Unrelated tracker" not in page.data
    assert page.data.count(b'<span class="role-tag">Editor</span>') == 2


# --- B. Card labels -------------------------------------------------------------------------------------------------


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
    assert "Business line and regions not set" in page
    assert f'data-regions=" {apac.id} {emea.id} "' in page or f'data-regions=" {emea.id} {apac.id} "' in page
    assert 'data-regions=" none "' in page
    assert f'data-line="{line.id}"' in page
    assert 'data-line="none"' in page
    # Two cards and two list rows carry the filter data.
    assert page.count("data-regions=") == 4 and page.count("data-line=") == 4


@pytest.mark.parametrize(
    "labelled, subtitle",
    [(True, "Desktop · Tradition brokerage · EMEA"), (False, "Desktop · Business line and regions not set")],
    ids=["labels set", "labels not set"],
)
def test_card_subtitle_puts_the_team_first(
    client,
    logged_in_admin,
    db,
    tracker_factory,
    team_factory,
    region_factory,
    business_line_factory,
    labelled,
    subtitle,
):
    tracker = tracker_factory(name="Teamed", team_id=team_factory(name="Desktop").id)
    if labelled:
        tracker.business_line_id = business_line_factory().id
        set_tracker_regions(db, tracker.id, [region_factory("EMEA").id])
        db.commit()
    page = text_of(client.get("/"))
    assert f'<p class="tracker-card-team">{subtitle}</p>' in page
    # The list view's tracker cell shows the same line.
    assert f'<span class="cell-sub">{subtitle}</span>' in page


# --- C. Filter options ----------------------------------------------------------------------------------------------


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


# --- E. Progress and dates ------------------------------------------------------------------------------------------


def test_home_shows_last_entry_date_and_percent(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory(name="Shown")
    grant(logged_in_user, tracker, "viewer")
    group = make_group(db, tracker, baseline=40)
    add_entry(db, tracker, group, date(2026, 9, 3), 10, date(2026, 9, 4))
    page = client.get("/")
    assert b"03 Sep 2026" in page.data
    assert b"25%" in page.data


def test_home_card_for_a_tracker_not_started_yet(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory(name="Later", first_week_ending=date(2099, 1, 2), last_week_ending=date(2099, 3, 27))
    grant(logged_in_user, tracker, "viewer")
    html = client.get("/").get_data(as_text=True)
    assert "Starts 02 Jan 2099" in html and "not written" not in html and 'class="spark"' not in html


def test_home_card_shows_the_target_when_there_is_no_forecast(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory(name="Mine", target_completion=date(2026, 12, 18))
    grant(logged_in_user, tracker, "viewer")
    card = cards_by_name(client.get("/").get_data(as_text=True))["Mine"]
    assert '<span class="fact-value">Not yet</span>' in card
    assert '<span class="fact-sub fact-line">Target 18 Dec 2026</span>' in card


def test_home_shows_one_chart_key_for_the_page(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory(name="Charted")
    grant(logged_in_user, tracker, "viewer")
    group = make_group(db, tracker, baseline=40)
    add_entry(db, tracker, group, date(2026, 9, 3), 10, date(2026, 9, 4))
    html = client.get("/").get_data(as_text=True)
    assert 'class="spark"' in html and "Latest week" not in html
    assert html.count('class="spark-key') == 1  # one chart key for the page, not one per card


# --- F. Status and alerts -------------------------------------------------------------------------------------------


def test_home_shows_weekly_status_from_latest_input(client, logged_in_user, db, tracker_factory, grant):
    tracker = tracker_factory(name="Rated")
    grant(logged_in_user, tracker, "viewer")
    assert "Not set" in client.get("/").get_data(as_text=True)
    db.add(ReportInput(tracker_id=tracker.id, week_ending=date(2026, 9, 4), status="Red"))
    db.add(ReportInput(tracker_id=tracker.id, week_ending=date(2026, 9, 11), status="Green"))
    db.commit()
    html = client.get("/").get_data(as_text=True)
    assert "tracker-card tracker-card-green" in html
    assert "tracker-card-red" not in html


def test_home_card_warns_when_the_weekly_update_is_not_written(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory(name="Unwritten")
    grant(logged_in_user, tracker, "viewer")
    html = client.get("/").get_data(as_text=True)
    assert re.search(r"Weekly update for \d\d \w{3} \d{4} not written", html)


def test_cards_flag_a_status_the_forecast_disagrees_with(client, logged_in_admin, db, monkeypatch, tracker_factory):
    """Green while 3 weeks behind is a warning and comes before Amber; Red while on track is a milder note."""
    days = {"Slipping": 21, "Steady": 0, "Worried": 0, "Amber one": 21}
    statuses = {"Slipping": "Green", "Steady": "Green", "Worried": "Red", "Amber one": "Amber"}
    for name, status in statuses.items():
        tracker = tracker_factory(name=name)
        db.add(ReportInput(tracker_id=tracker.id, week_ending=date(2026, 9, 4), status=status))
    db.commit()
    real = build.compute_position  # the home view imports it from there when it runs

    def position(session, tracker, *args):
        found = real(session, tracker, *args)
        headline = dataclasses.replace(
            found.headline, forecast_vs_target_days=days[tracker.name], total_scope=10, remaining=5
        )
        return found._replace(headline=headline)

    monkeypatch.setattr(build, "compute_position", position)
    page = client.get("/").get_data(as_text=True)
    by_name = cards_by_name(page)
    assert "Green, but the forecast is 3 weeks behind target</span>" in by_name["Slipping"]
    assert 'class="alert alert-warn"' in by_name["Slipping"] and 'data-disagree="true"' in by_name["Slipping"]
    assert "tracker-card-disagree" in by_name["Slipping"] and 'class="verdict-pill is-warning"' in by_name["Slipping"]
    assert "Red, but the forecast is on track for target</span>" in by_name["Worried"]
    assert 'data-disagree="false"' in by_name["Worried"] and "tracker-card-disagree" not in by_name["Worried"]
    assert "but the forecast" not in by_name["Steady"] + by_name["Amber one"]
    order = list(by_name)
    assert order.index("Worried") < order.index("Slipping") < order.index("Amber one") < order.index("Steady")
    rows = re.findall(r'<tr class="tracker-row.*?</tr>', page, re.S)
    slipping = next(row for row in rows if ">Slipping<" in row)
    assert '<span class="cell-sub flag">Green, but the forecast is 3 weeks behind target</span>' in slipping


# --- G. Risks -------------------------------------------------------------------------------------------------------


def test_home_card_counts_only_open_red_risks(client, logged_in_user, db, tracker_factory, grant):
    risky, calm = tracker_factory(name="Risky"), tracker_factory(name="Calm")
    grant(logged_in_user, risky, "viewer")
    grant(logged_in_user, calm, "viewer")
    db.add_all(
        [
            Risk(tracker_id=risky.id, ref="R1", description="a", rag="Red"),
            Risk(tracker_id=risky.id, ref="R2", description="b", rag="Red", status="Closed"),
            Risk(tracker_id=risky.id, ref="R3", description="c", rag="Amber"),
        ]
    )
    db.commit()
    by_name = cards_by_name(client.get("/").get_data(as_text=True))
    assert '<span class="fact-value tone-danger">1</span><span class="fact-sub">2 open risks</span>' in by_name["Risky"]
    assert "No open risks" in by_name["Calm"]


# --- H. Role, actions and person in charge --------------------------------------------------------------------------


def test_home_card_for_an_editor_has_record_and_update_links(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory(name="Editable")
    grant(logged_in_user, tracker, "editor")
    html = client.get("/").get_data(as_text=True)
    assert '<span class="role-tag">Editor</span>' in html
    assert f'href="/trackers/{tracker.id}/entries/new"' in html
    assert (
        re.search(rf'href="/trackers/{tracker.id}/inputs\?week=\d{{4}}-\d\d-\d\d"', html) and "Write the update" in html
    )


def test_home_card_for_a_viewer_has_no_record_link(client, logged_in_user, tracker_factory, grant):
    tracker = tracker_factory(name="Read only")
    grant(logged_in_user, tracker, "viewer")
    html = client.get("/").get_data(as_text=True)
    assert f'href="/trackers/{tracker.id}/entries/new"' not in html and "Write the update" not in html
    assert '<span class="role-tag">Viewer</span>' in html


def test_home_card_names_the_person_in_charge(client, logged_in_user, db, tracker_factory, grant, user_factory):
    mine, theirs, unled = (tracker_factory(name=name) for name in ("Mine", "Theirs", "Unled"))
    other = user_factory(full_name="Bea Lead")
    grant(logged_in_user, mine, "owner")
    grant(logged_in_user, theirs, "viewer")
    grant(logged_in_user, unled, "viewer")
    grant(other, theirs, "editor")
    mine.lead_user_id, theirs.lead_user_id = logged_in_user.id, other.id
    db.commit()
    by_name = cards_by_name(client.get("/").get_data(as_text=True))
    assert "In charge: <strong>You</strong>" in by_name["Mine"]
    assert "In charge: <strong>Bea Lead</strong>" in by_name["Theirs"]
    assert "In charge: <strong" not in by_name["Unled"] and "Nobody yet" in by_name["Unled"]


def test_new_tracker_button_follows_create_trackers(client, logged_in_user, give_set):
    assert 'href="/trackers/new"' not in client.get("/").get_data(as_text=True)
    give_set(["create_trackers"], user=logged_in_user)
    assert 'href="/trackers/new"' in client.get("/").get_data(as_text=True)
