from tracker.lists.catalogue import (
    BUSINESS_LINE_CHOICE_ERROR,
    BUSINESS_LINE_REQUIRED,
    LOCATION_CHOICE_ERROR,
    LOCATION_REGION_MISMATCH,
    LOCATION_REQUIRED,
    REGIONS_CHOICE_ERROR,
    REGIONS_REQUIRED,
    TrackerLabels,
    location_choices,
    location_label,
    parse_business_line,
    parse_location,
    parse_regions,
    set_tracker_regions,
    team_places,
    tracker_labels,
)


def test_parse_location_refuses_a_location_from_another_region(db, region_factory, location_factory):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    geneva = location_factory(emea)
    assert parse_location(db, str(apac.id), str(geneva.id), None) == (None, LOCATION_REGION_MISMATCH)
    assert parse_location(db, str(emea.id), str(geneva.id), None) == (geneva, None)
    assert parse_location(db, "", str(geneva.id), None) == (None, LOCATION_REQUIRED)
    assert parse_location(db, str(emea.id), "99999999999", None) == (None, LOCATION_CHOICE_ERROR)


def test_a_retired_location_is_accepted_only_where_it_is_already_used(db, region_factory, location_factory):
    emea = region_factory("EMEA")
    old = location_factory(emea, city="Zurich", retired=True)
    assert parse_location(db, str(emea.id), str(old.id), None) == (None, LOCATION_CHOICE_ERROR)
    assert parse_location(db, str(emea.id), str(old.id), old.id) == (old, None)
    assert [o.code for o in location_choices(db)] == ["EMEA"] and location_choices(db)[0].locations == []
    assert location_choices(db, keep_id=old.id)[0].locations == [(old.id, "Zurich, Switzerland", True)]


def test_a_kept_location_in_a_retired_region_reads_as_retired(db, region_factory, location_factory):
    gone = region_factory("LATAM", retired=True)
    kept = location_factory(gone, city="Lima", country_code="PE")
    assert location_choices(db) == []
    options = location_choices(db, keep_id=kept.id)
    assert [(o.code, o.retired) for o in options] == [("LATAM", True)]
    assert options[0].locations == [(kept.id, "Lima, Peru", True)]
    assert parse_location(db, str(gone.id), str(kept.id), None) == (None, LOCATION_CHOICE_ERROR)
    assert parse_location(db, str(gone.id), str(kept.id), kept.id) == (kept, None)


def test_parse_regions_requires_one_and_refuses_unknown_and_retired(db, region_factory):
    emea, gone = region_factory("EMEA"), region_factory("LATAM", retired=True)
    assert parse_regions(db, [], ()) == ([], REGIONS_REQUIRED)
    assert parse_regions(db, [str(emea.id), "x"], ()) == ([], REGIONS_CHOICE_ERROR)
    assert parse_regions(db, [str(gone.id)], ()) == ([], REGIONS_CHOICE_ERROR)
    assert parse_regions(db, [str(gone.id), str(emea.id), str(emea.id)], {gone.id}) == ([emea, gone], None)


def test_parse_business_line(db, business_line_factory):
    line, old = business_line_factory(), business_line_factory("Old line", retired=True)
    assert parse_business_line(db, "", None) == (None, BUSINESS_LINE_REQUIRED)
    assert parse_business_line(db, str(old.id), None) == (None, BUSINESS_LINE_CHOICE_ERROR)
    assert parse_business_line(db, str(old.id), old.id) == (old, None)
    assert parse_business_line(db, str(line.id), None) == (line, None)


def test_tracker_labels_and_team_places(
    db, tracker_factory, team_factory, region_factory, location_factory, business_line_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    team = team_factory("Desktop", location_id=location_factory(emea).id)
    unset = tracker_factory(name="Unset")
    labelled = tracker_factory(name="Labelled", business_line_id=business_line_factory().id)
    set_tracker_regions(db, labelled.id, [emea.id, apac.id])
    db.commit()
    assert tracker_labels(db, [unset.id, labelled.id]) == {
        unset.id: TrackerLabels(None, []),
        labelled.id: TrackerLabels("Tradition brokerage", ["APAC", "EMEA"]),
    }
    assert team_places(db)[team.id].location == "Geneva, Switzerland"
    assert team_places(db)[team.id].region_code == "EMEA"


def test_location_label_names_the_country_or_leaves_it_out():
    assert location_label("Geneva", "CH") == "Geneva, Switzerland"
    assert location_label("Geneva", None) == "Geneva"
