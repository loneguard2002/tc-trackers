from pathlib import Path

from tracker.lists.countries import (
    COUNTRIES,
    COUNTRY_CHOICE_ERROR,
    COUNTRY_REQUIRED,
    country_name,
    flag_path,
    match_country,
    parse_country,
)


def test_list_has_every_iso_code_once_sorted_by_name():
    assert len(COUNTRIES) == 249
    assert all(len(c) == 2 and c.isupper() for c in COUNTRIES)
    names = list(COUNTRIES.values())
    assert names == sorted(names, key=str.casefold)


def test_names():
    assert country_name("GB") == "United Kingdom"
    assert country_name("us") == "United States"
    assert country_name("CH") == "Switzerland"
    assert country_name("XX") is None and country_name(None) is None and country_name("") is None


def test_match_country_names_codes_and_aliases():
    for text, code in [
        ("United Kingdom", "GB"),
        (" uk ", "GB"),
        ("USA", "US"),
        ("United States of America", "US"),
        ("united arab emirates", "AE"),
        ("UAE", "AE"),
        ("ch", "CH"),
        ("Switzerland", "CH"),
    ]:
        assert match_country(text) == code
    assert match_country("Atlantis") is None and match_country("") is None and match_country(None) is None


def test_parse_country():
    assert parse_country(" gb ") == ("GB", None)
    assert parse_country("") == (None, COUNTRY_REQUIRED)
    assert parse_country("ZZ") == (None, COUNTRY_CHOICE_ERROR)
    assert parse_country("United Kingdom") == (None, COUNTRY_CHOICE_ERROR)


def test_every_country_has_a_flag_file():
    root = Path(__file__).parent.parent / "tracker" / "static"
    assert all((root / flag_path(code)).is_file() for code in COUNTRIES)
    assert (root / "flags" / "LICENSE-flag-icons.txt").is_file()
