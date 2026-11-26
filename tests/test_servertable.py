"""The shared server-side table pieces: the state read from the address, the search pattern, the page window and
the footer and heading macros."""

from __future__ import annotations

from urllib.parse import urlencode

import pytest
from flask import render_template_string
from werkzeug.datastructures import MultiDict

from tracker.servertable import (
    TableState,
    clamp_page,
    like_pattern,
    page_numbers,
    read_state,
    sort_changes,
    state_args,
)

KEYS = ("time", "person")


def read(**args):
    return read_state(MultiDict(args), KEYS, "time", True)


def test_defaults():
    assert read() == TableState(q="", sort="time", descending=True, page=1, size=25)


def test_search_text_is_stripped_and_capped():
    assert read(q="  roster ").q == "roster"
    assert len(read(q="x" * 500).q) == 200


def test_a_bad_size_is_25_and_a_good_one_is_kept():
    assert read(size="7").size == 25
    assert read(size="abc").size == 25
    assert read(size="100").size == 100


def test_sort_prefix_means_descending_and_unknown_keys_use_the_default():
    assert (read(sort="-person").sort, read(sort="-person").descending) == ("person", True)
    assert (read(sort="person").sort, read(sort="person").descending) == ("person", False)
    assert (read(sort="-time").sort, read(sort="-time").descending) == ("time", True)
    unknown = read(sort="-nonsense")
    assert (unknown.sort, unknown.descending) == ("time", True)


def test_a_page_that_is_not_a_number_is_1_and_never_below_1():
    assert read(page="abc").page == 1
    assert read(page="0").page == 1
    assert read(page="-3").page == 1
    assert read(page="4").page == 4


def test_hostile_input_never_raises_and_q_has_no_nul():
    state = read(page="9" * 5000, q="a\x00b")
    assert "\x00" not in state.q and state.q == "ab"
    assert read(page="٣").page == 1  # an Arabic-Indic digit is not read as a number
    assert read(page="-1").page == 1
    assert read(page="9" * 5000).page == 10**9  # the last page, once clamped
    assert read(q="\x00").q == ""


def test_like_pattern_escapes_the_wildcards():
    assert like_pattern("50%_a\\b") == "%50\\%\\_a\\\\b%"
    assert like_pattern("plain") == "%plain%"


def test_clamp_page():
    state = read(page="999")
    assert clamp_page(state, 60).page == 3
    assert clamp_page(state, 0).page == 1
    assert clamp_page(read(page="2"), 60).page == 2
    assert clamp_page(read(page="2", size="100"), 60).page == 1


def test_page_numbers():
    assert page_numbers(1, 1) == [1]
    assert page_numbers(2, 3) == [1, 2, 3]
    assert page_numbers(5, 20) == [1, None, 4, 5, 6, None, 20]
    assert page_numbers(1, 20) == [1, 2, None, 20]
    assert page_numbers(20, 20) == [1, None, 19, 20]
    assert page_numbers(3, 5) == [1, 2, 3, 4, 5]


def test_state_args_leaves_out_the_defaults():
    state = read()
    assert state_args(state, "time", True) == {}
    assert state_args(state, "time", True, page=1, size=25, sort="time", descending=True) == {}
    assert state_args(state, "time", True, page=3, size=50, q="a b") == {"page": 3, "size": 50, "q": "a b"}
    assert state_args(state, "time", True, sort="person", descending=False) == {"sort": "person"}
    assert state_args(state, "time", True, sort="person", descending=True) == {"sort": "-person"}
    assert state_args(state, "time", True, descending=False) == {"sort": "time"}


def test_sort_changes_reverse_the_sorted_column_and_restart_at_page_1():
    state = read(page="4")
    assert sort_changes(state, "time") == {"sort": "time", "descending": False, "page": 1}
    assert sort_changes(state, "person") == {"sort": "person", "descending": False, "page": 1}
    ascending = read(sort="person")
    assert sort_changes(ascending, "person")["descending"] is True


@pytest.fixture
def render(app):
    def go(source, **context):
        with app.test_request_context("/"):
            return render_template_string(
                '{% from "lists/_table.html" import server_pager, server_sort_header %}' + source, **context
            )

    return go


def page_url(n):
    return "/activity?" + urlencode({"page": n, "q": "a&b"})


FOOTER = "{{ server_pager(state, total, 'entries', 'entry', page_url, size_form, first, last, extra) }}"


def footer(render, *, page=1, total=312, size=25, size_form=None, extra="", **more):
    state = TableState(q="", sort="time", descending=True, page=page, size=size)
    first = (page - 1) * size + 1
    last = min(total, page * size)
    return render(
        more.get("source", FOOTER),
        state=state,
        total=total,
        page_url=page_url,
        size_form=size_form,
        first=first,
        last=last,
        extra=extra,
    )


def test_sort_header_is_a_link_with_aria_sort(render):
    source = (
        "{{ server_sort_header('Time', 'time', state, '/next', 'wide') }}"
        "{{ server_sort_header('Person', 'person', state, '/p') }}"
    )
    html = render(source, state=read(sort="-time"))
    assert '<th scope="col" class="wide" aria-sort="descending"><a class="sort-button" href="/next">Time' in html
    assert '<th scope="col" aria-sort="none"><a class="sort-button" href="/p">Person' in html
    ascending = render(source, state=read(sort="time"))
    assert 'aria-sort="ascending"' in ascending


def test_footer_text_for_a_middle_page(render):
    html = footer(render, page=2, size_form={"q": "a"})
    assert "Showing 26–50 of 312 entries" in html
    assert 'aria-current="page"' in html
    assert html.count('aria-current="page"') == 1
    assert 'href="/activity?page=1&amp;q=a%26b"' in html  # escaped in the attribute
    assert '<span class="pager-gap">…</span>' in html
    assert 'rel="prev"' in html and 'rel="next"' in html


def test_footer_ends_are_disabled_spans_not_links(render):
    first = footer(render, page=1)
    assert '<span class="pager-button is-disabled" aria-disabled="true">Previous</span>' in first
    assert 'rel="prev"' not in first
    last = footer(render, page=13)
    assert '<span class="pager-button is-disabled" aria-disabled="true">Next</span>' in last
    assert "Showing 301–312 of 312 entries" in last


def test_footer_page_past_the_last_is_shown_as_the_last(render):
    html = footer(render, page=99, total=60)
    assert html.count('aria-current="page"') == 1
    assert 'aria-label="Page 3" aria-current="page"' in html


def test_footer_one_page_has_no_controls(render):
    html = footer(render, total=3, size_form={})
    assert "Showing 3 of 3 entries" in html
    assert "pager-controls" not in html
    assert "Showing 1 of 1 entry" in footer(render, total=1, size_form={})
    assert "Showing 0 of 0 entries" in footer(render, total=0, size_form={})


def test_footer_one_page_counts_the_matches_of_all_the_rows(render):
    source = "{{ server_pager(state, 3, 'entries', 'entry', page_url, none, 1, 3, overall=312) }}"
    assert "Showing 3 of 312 entries" in footer(render, source=source)
    none = "{{ server_pager(state, 0, 'entries', 'entry', page_url, none, 1, 0, overall=312) }}"
    assert "Showing 0 of 312 entries" in footer(render, source=none)
    one_of_one = "{{ server_pager(state, 1, 'entries', 'entry', page_url, none, 1, 1, overall=1) }}"
    assert "Showing 1 of 1 entry" in footer(render, source=one_of_one)
    many = "{{ server_pager(state, 40, 'entries', 'entry', page_url, none, 1, 25, overall=312) }}"
    assert "Showing 1–25 of 40 entries" in footer(render, source=many)  # more than a page: of the matches only


def test_footer_extra_text(render):
    html = footer(render, extra="214 entries", total=40)
    assert "Showing 1–25 of 40 entries · 214 entries" in html


def test_footer_noun_first_for_a_table_paged_by_weeks(render):
    source = "{{ server_pager(state, 23, 'weeks', 'week', page_url, none, 1, 10, '214 entries', noun_first=True) }}"
    html = footer(render, size=10, source=source)
    assert "Showing weeks 1–10 of 23 · 214 entries" in html
    one_page = (
        "{{ server_pager(state, 4, 'weeks', 'week', page_url, none, 1, 4, '31 entries', noun_first=True, overall=23) }}"
    )
    assert "Showing 4 of 23 weeks · 31 entries" in footer(render, size=10, source=one_page)
    assert "Rows per page" not in html
    assert 'aria-current="page"' in html


def test_footer_size_form_keeps_the_other_keys(render):
    html = footer(render, size=50, size_form={"q": "a b", "sort": "-person"})
    assert '<form class="pager-size-form" method="get">' in html
    assert '<input type="hidden" name="q" value="a b">' in html
    assert '<input type="hidden" name="sort" value="-person">' in html
    assert '<select name="size" data-autosubmit>' in html
    assert '<option value="50" selected>50</option>' in html
    assert "data-autosubmit-fallback" in html
    assert 'name="page"' not in html


def test_the_size_control_stays_when_a_large_size_fits_one_page(render):
    html = footer(render, total=60, size=100, size_form={})
    assert "Rows per page" in html
    assert "Showing 60 of 60 entries" in html
    assert "Previous" in html
