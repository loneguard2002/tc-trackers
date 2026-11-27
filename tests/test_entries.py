"""Data entry routes: completions, targets, weekly inputs, risks (database required)."""

import re
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

from sqlalchemy import select

from tests.conftest import post
from tracker.engine.calc import group_positions
from tracker.models import AuditLog, CompletionEntry, Group, ReportInput, ReportSend, Risk, TrackerRole, Week
from tracker.trackers import load_engine_inputs

OUTSIDE = "That date is outside this tracker&#39;s weeks (04 Sep 2026 to 25 Dec 2026)."


def setup_editor(db, tracker_factory, user_factory, grant, client, role="editor", **tracker_kw):
    from tests.conftest import sign_in

    tracker = tracker_factory(**tracker_kw)
    user = user_factory()
    grant(user, tracker, role)
    sign_in(client, user)
    group = Group(tracker_id=tracker.id, name="Site A", baseline=50)
    db.add(group)
    db.commit()
    return tracker, user, group


def entry_url(tracker, suffix=""):
    return f"/trackers/{tracker.id}/entries{suffix}"


def entry_form(group, entry_date="2026-10-14", quantity="5", note=""):
    return {"group_id": str(group.id), "entry_date": entry_date, "quantity": quantity, "note": note}


def test_entry_assigned_to_week_ending(client, db, tracker_factory, user_factory, grant):
    tracker, user, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, entry_url(tracker, "/new"), entry_form(group))  # Wednesday
    assert response.status_code == 302
    entry = db.scalars(select(CompletionEntry)).one()
    assert entry.week_ending == date(2026, 10, 16) and entry.created_by == user.id


def test_entry_dated_in_the_future_is_refused(client, db, tracker_factory, user_factory, grant):
    friday = date.today() - timedelta(days=(date.today().weekday() - 4) % 7)  # weeks around today, ending Fridays
    tracker, _, group = setup_editor(
        db,
        tracker_factory,
        user_factory,
        grant,
        client,
        first_week_ending=friday - timedelta(weeks=4),
        last_week_ending=friday + timedelta(weeks=4),
    )
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = post(client, entry_url(tracker, "/new"), entry_form(group, tomorrow))
    assert response.status_code == 400
    assert "The date cannot be after today" in response.get_data(as_text=True)
    assert db.scalars(select(CompletionEntry)).first() is None
    form = client.get(entry_url(tracker)).get_data(as_text=True)
    assert f'max="{date.today().isoformat()}"' in form[form.index("data-quick-add") :]


def test_entries_same_group_week_add_up(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-12", "5"))
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "7"))
    weeks, _, actuals, groups, totals = load_engine_inputs(db, tracker, date(2026, 10, 16))
    assert actuals[date(2026, 10, 16)] == 12
    assert group_positions(groups, totals)[0].deployed == 12


def test_entry_after_last_week_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, entry_url(tracker, "/new"), entry_form(group, "2026-12-26"))
    assert response.status_code == 400 and OUTSIDE.encode() in response.data
    assert db.scalars(select(CompletionEntry)).all() == []


def test_entry_before_first_week_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, entry_url(tracker, "/new"), entry_form(group, "2026-08-28"))
    assert response.status_code == 400 and OUTSIDE.encode() in response.data


def test_entry_on_retired_group_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    group.retired = True
    db.commit()
    response = post(client, entry_url(tracker, "/new"), entry_form(group))
    assert response.status_code == 400 and b"retired group" in response.data
    assert db.scalars(select(CompletionEntry)).all() == []


def test_entry_on_group_of_another_tracker_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = tracker_factory(name="Other")
    foreign = Group(tracker_id=other.id, name="Site B", baseline=5)
    db.add(foreign)
    db.commit()
    assert post(client, entry_url(tracker, "/new"), entry_form(foreign)).status_code == 400


def test_zero_or_negative_quantity_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    for bad in ("0", "-3", "1.5", ""):
        response = post(client, entry_url(tracker, "/new"), entry_form(group, quantity=bad))
        assert response.status_code == 400 and b"at least 1" in response.data
    assert db.scalars(select(CompletionEntry)).all() == []


def test_delete_entry_audited(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5"))
    entry = db.scalars(select(CompletionEntry)).one()
    response = post(client, entry_url(tracker, f"/{entry.id}/delete"))
    assert response.status_code == 302
    db.expire_all()
    assert db.scalars(select(CompletionEntry)).all() == []
    log = db.scalars(select(AuditLog).where(AuditLog.action == "entry_deleted")).one()
    assert log.detail == {"group_id": group.id, "entry_date": "2026-10-14", "quantity": 5}


def test_delete_entry_of_another_tracker_is_404(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = tracker_factory(name="Other")
    foreign = Group(tracker_id=other.id, name="Site B", baseline=5)
    db.add(foreign)
    db.commit()
    entry = CompletionEntry(
        tracker_id=other.id,
        group_id=foreign.id,
        entry_date=date(2026, 10, 14),
        week_ending=date(2026, 10, 16),
        quantity=2,
    )
    db.add(entry)
    db.commit()
    assert post(client, entry_url(tracker, f"/{entry.id}/delete")).status_code == 404


def test_entry_list_filters(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="first batch"))
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-21", "6", note="second batch"))
    page = client.get(entry_url(tracker) + "?week=2026-10-16").data
    assert b"first batch" in page and b"second batch" not in page


def test_entries_are_grouped_by_week_against_target(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 10, 16), target=10))
    db.commit()
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="first batch"))
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-21", "6", note="second batch"))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert html.index("Week ending 23 Oct 2026") < html.index("Week ending 16 Oct 2026")  # newest week first
    short = html[html.index("Week ending 16 Oct 2026") :]
    assert "<strong>5</strong> of 10 target" in short and "−5" in short and "week-block-bar is-low" in short
    assert "<strong>6</strong> recorded" in html  # no target set for the week ending 23 Oct
    assert html.count("1 entry<") == 2
    assert "tabulator" not in html and "tables.js" not in html


def test_entries_location_chips_count_and_filter(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=20)
    db.add(other)
    db.commit()
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="at A"))
    post(client, entry_url(tracker, "/new"), entry_form(other, "2026-10-14", "3", note="at B"))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    # The chips count devices, not entries, and say so.
    assert 'aria-current="true">All locations<span class="chip-count">8</span>' in html
    assert 'Site B<span class="chip-count">3</span>' in html
    assert '<span class="chip-label" id="chips-label">Devices recorded by location</span>' in html
    # The columns are named on screen, not only for screen readers.
    assert '<thead class="sr-only">' not in html
    assert '<th scope="col" aria-sort="descending"><a class="sort-button" href="' in html
    assert ">Location<" in html and 'class="num" aria-sort="none"' in html
    html = client.get(entry_url(tracker) + f"?group={other.id}").get_data(as_text=True)
    assert "at B" in html and "at A" not in html
    assert "<strong>3</strong> recorded at Site B" in html


def quick_add(html: str) -> str:
    """The quick-add form of an Entries page."""
    return html[html.index("data-quick-add") : html.index('id="section-entries"')]


def test_the_old_full_form_address_opens_the_entries_page(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = client.get(entry_url(tracker, f"/new?group={group.id}"))
    assert response.status_code == 302 and response.headers["Location"].endswith(entry_url(tracker))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert "Full form" not in html and 'name="return_to"' not in html


def test_record_keeps_the_location_and_date_for_the_next_entry(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=20)
    db.add(other)
    db.commit()
    filters = {"filter_week": "2026-10-16", "filter_group": str(other.id)}
    form = {**entry_form(other, "2026-10-14", "3", note="n"), **filters}
    response = post(client, entry_url(tracker, "/new"), form)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(entry_url(tracker, f"?week=2026-10-16&group={other.id}"))
    entry = db.scalars(select(CompletionEntry)).one()
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    form_html = quick_add(html)
    assert re.search(rf'<option value="{other.id}"\s+selected>Site B</option>', form_html)
    assert not re.search(rf'<option value="{group.id}"\s+selected>', form_html)
    assert re.search(r'id="qa-date"[^>]*value="2026-10-14"', form_html)
    assert re.search(r'id="qa-quantity"[^>]*autofocus', form_html)
    assert 'id="qa-note" name="note" value=""' in form_html  # the note starts empty again
    assert "Recorded 3 for Site B on 14 Oct 2026." in form_html
    assert f'<tr class="is-new" data-entry="{entry.id}">' in html
    # The next visit starts fresh: today's date, no location, no result line, no highlight.
    again = client.get(entry_url(tracker)).get_data(as_text=True)
    assert "Recorded 3" not in again and "is-new" not in again and "autofocus" not in quick_add(again)
    assert not re.search(r"<option value=\"\d+\"\s+selected>", quick_add(again))


def test_the_last_record_belongs_to_its_own_tracker(client, db, tracker_factory, user_factory, grant):
    tracker, user, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    second = tracker_factory(name="Second")
    grant(user, second, "editor")
    db.add(Group(tracker_id=second.id, name="Site Z", baseline=5))
    db.commit()
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "4"))
    assert "Recorded 4" not in client.get(entry_url(second)).get_data(as_text=True)
    assert "Recorded 4 for Site A" in client.get(entry_url(tracker)).get_data(as_text=True)


def test_record_ignores_filters_it_cannot_read(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    form = {**entry_form(group), "filter_week": "soon", "filter_group": "x"}
    response = post(client, entry_url(tracker, "/new"), form)
    assert response.status_code == 302 and response.headers["Location"].endswith(entry_url(tracker))


def test_a_refused_entry_comes_back_on_the_entries_page(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "0", note="keep me"))
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    form_html = quick_add(html)
    assert form_html.count("at least 1") == 1 and 'id="section-entries"' in html
    assert re.search(rf'<option value="{group.id}"\s+selected>Site A</option>', form_html)
    assert re.search(r'id="qa-date"[^>]*value="2026-10-14"', form_html)
    assert re.search(r'id="qa-quantity"[^>]*value="0"', form_html)
    assert 'value="keep me"' in form_html


def test_entries_csv_follows_the_filters(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="=HYPERLINK(1)"))
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-21", "6", note="later"))
    response = client.get(entry_url(tracker, ".csv"))
    assert response.mimetype == "text/csv" and "filename=entries.csv" in response.headers["Content-Disposition"]
    lines = response.get_data(as_text=True).lstrip("\ufeff").splitlines()
    assert lines[0] == "Date,Week ending,Location,Quantity,Note"
    assert lines[1:] == ["2026-10-21,2026-10-23,Site A,6,later", "2026-10-14,2026-10-16,Site A,5,'=HYPERLINK(1)"]
    lines = client.get(entry_url(tracker, ".csv?week=2026-10-23")).get_data(as_text=True).splitlines()
    assert len(lines) == 2 and lines[1].endswith(",later")


def weekly_entries(db, tracker, group, weeks: int, per_week: int = 1, user=None, note="n"):
    """``per_week`` entries in each of ``weeks`` weeks ending on Fridays, from 2026-01-02; returns the week endings."""
    endings = [date(2026, 1, 2) + timedelta(weeks=n) for n in range(weeks)]
    for n, ending in enumerate(endings):
        for k in range(per_week):
            db.add(
                CompletionEntry(
                    tracker_id=tracker.id,
                    group_id=group.id,
                    entry_date=ending - timedelta(days=k % 5),
                    week_ending=ending,
                    quantity=1 + k,
                    note=f"{note} {n}-{k}",
                    created_by=user.id if user else None,
                )
            )
    db.commit()
    return endings


def long_tracker(db, tracker_factory, user_factory, grant, client):
    return setup_editor(
        db,
        tracker_factory,
        user_factory,
        grant,
        client,
        first_week_ending=date(2026, 1, 2),
        last_week_ending=date(2026, 12, 25),
    )


def shown_weeks(html: str) -> list[str]:
    return re.findall(r'week-block-title">Week ending (\d\d \w{3} 2026)<', html)


def test_entries_page_by_weeks_with_the_standard_footer(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 23, per_week=2)
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert len(shown_weeks(html)) == 10 and shown_weeks(html)[0] == "05 Jun 2026"  # the newest 10 of 23
    assert "Showing weeks 1–10 of 23 · 46 entries" in " ".join(html.split())
    assert "Rows per page" not in html and 'aria-label="Page 3"' in html
    html = client.get(entry_url(tracker, "?page=3")).get_data(as_text=True)
    assert len(shown_weeks(html)) == 3 and shown_weeks(html)[-1] == "02 Jan 2026"
    assert "Showing weeks 21–23 of 23 · 46 entries" in " ".join(html.split())
    assert shown_weeks(client.get(entry_url(tracker, "?page=99")).get_data(as_text=True)) == shown_weeks(html)


def test_a_week_on_the_page_shows_every_entry(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 1, per_week=600)
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert html.count('class="entry-date"') == 600 and "Showing the latest" not in html
    assert "Showing 1 of 1 week · 600 entries" in " ".join(html.split())


def test_entries_search_matches_location_names_and_notes(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Harbour 100%", baseline=1)
    db.add(other)
    db.commit()
    weekly_entries(db, tracker, group, 3, note="routine")
    weekly_entries(db, tracker, other, 1, note="harbour work")
    by_name = client.get(entry_url(tracker, "?q=harbour+100%25")).get_data(as_text=True)
    assert "harbour work" in by_name and "routine" not in by_name
    by_note = client.get(entry_url(tracker, "?q=ROUTINE")).get_data(as_text=True)
    assert "routine 0-0" in by_note and "harbour work" not in by_note
    # A percent sign or underscore matches itself only; a quote does not break the query.
    flat = " ".join(client.get(entry_url(tracker, "?q=%25")).get_data(as_text=True).split())
    assert "Showing 1 of 3 weeks · 1 entry" in flat  # only the location whose name holds a percent sign
    assert "routine" not in client.get(entry_url(tracker, "?q=r_utine")).get_data(as_text=True)
    assert client.get(entry_url(tracker, "?q=%27%22%5C")).status_code == 200


def test_the_footer_counts_only_the_weeks_and_entries_that_match(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=1)
    db.add(other)
    db.commit()
    weekly_entries(db, tracker, group, 12, per_week=2, note="alpha")
    weekly_entries(db, tracker, other, 2, per_week=3, note="beta")  # the first two weeks also have Site B entries
    flat = lambda url: " ".join(client.get(entry_url(tracker, url)).get_data(as_text=True).split())  # noqa: E731
    assert "Showing weeks 1–10 of 12 · 30 entries" in flat("")
    assert "Showing 2 of 12 weeks · 6 entries" in flat(f"?group={other.id}")
    assert "Showing 2 of 12 weeks · 6 entries" in flat("?q=beta")
    assert "Showing 1 of 12 weeks · 3 entries" in flat(f"?group={other.id}&week=2026-01-09&q=beta")
    assert "Showing 0 of 12 weeks · 0 entries" in flat(f"?group={group.id}&q=beta")
    # A week is never split: filtering to a location keeps every matching entry of each week it shows.
    html = client.get(entry_url(tracker, f"?group={other.id}")).get_data(as_text=True)
    assert html.count("beta ") == 6


def test_the_chips_follow_the_search_and_the_week(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=1)
    db.add(other)
    db.commit()
    weekly_entries(db, tracker, group, 2, per_week=2, note="alpha")  # 1 + 2 = 3 a week
    weekly_entries(db, tracker, other, 2, per_week=1, note="beta")  # 1 a week
    html = client.get(entry_url(tracker, "?q=alpha")).get_data(as_text=True)
    assert 'aria-current="true">All locations<span class="chip-count">6</span>' in html
    assert 'Site B<span class="chip-count">0</span>' in html
    assert f'href="/trackers/{tracker.id}/entries?group={other.id}&amp;q=alpha"' in html  # the chip keeps the search
    html = client.get(entry_url(tracker, "?week=2026-01-02&q=alpha")).get_data(as_text=True)
    assert 'aria-current="true">All locations<span class="chip-count">3</span>' in html


def test_sorting_orders_the_rows_inside_each_week_and_the_weeks_stay_newest_first(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 2, per_week=3)  # quantities 1, 2, 3 in each week
    html = client.get(entry_url(tracker, "?sort=quantity")).get_data(as_text=True)
    assert shown_weeks(html) == ["09 Jan 2026", "02 Jan 2026"]
    assert re.findall(r'class="num" data-label="Quantity">(\d)<', html) == ["1", "2", "3", "1", "2", "3"]
    html = client.get(entry_url(tracker, "?sort=-quantity")).get_data(as_text=True)
    assert shown_weeks(html) == ["09 Jan 2026", "02 Jan 2026"]
    assert re.findall(r'class="num" data-label="Quantity">(\d)<', html) == ["3", "2", "1", "3", "2", "1"]
    assert re.findall(
        r'class="num" data-label="Quantity">(\d)<', client.get(entry_url(tracker)).get_data(as_text=True)
    )[:3] == [
        "1",
        "2",
        "3",
    ]  # newest first by date: the entry dated on the Friday has quantity 1
    assert 'aria-sort="descending"><a class="sort-button"' in html
    assert f'href="/trackers/{tracker.id}/entries?sort=quantity"' in html  # a click on the sorted column reverses it
    assert client.get(entry_url(tracker, "?sort=bogus")).status_code == 200


def test_sort_by_location_uses_the_location_name(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Alpha site", baseline=1)
    db.add(other)
    db.commit()
    weekly_entries(db, tracker, group, 1, note="at A")
    weekly_entries(db, tracker, other, 1, note="at alpha")
    html = client.get(entry_url(tracker, "?sort=location")).get_data(as_text=True)
    assert html.index("at alpha") < html.index("at A ")


def test_entry_cells_carry_labels_for_the_phone_cards(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 1)
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    for label in ("Date", "Location", "Quantity", "Note"):
        assert f'data-label="{label}"' in html


def test_every_link_keeps_the_search_sort_and_page(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 12, note="alpha")
    html = client.get(entry_url(tracker, f"?q=alpha&sort=-note&page=2&group={group.id}")).get_data(as_text=True)
    assert 'name="filter_q" value="alpha"' in html and 'name="filter_sort" value="-note"' in html
    assert 'name="filter_page" value="2"' in html
    csv_link = html.split("/entries.csv")[1].split('"')[0]
    assert f"group={group.id}" in csv_link and "q=alpha" in csv_link
    form = html[html.index('class="entry-week"') :].split("</form>")[0]
    assert 'name="q" value="alpha"' in form and 'name="sort" value="-note"' in form and 'name="group"' in form


def test_a_refused_record_keeps_the_search_sort_and_page(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 12, note="alpha")
    filters = {"filter_q": "alpha", "filter_sort": "-note", "filter_page": "2", "filter_group": str(group.id)}
    response = post(client, entry_url(tracker, "/new"), {**entry_form(group, "2026-01-07", "0"), **filters})
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert 'name="filter_q" value="alpha"' in html and 'name="filter_page" value="2"' in html
    assert "Showing weeks 11–12 of 12" in " ".join(html.split())
    response = post(client, entry_url(tracker, "/new"), {**entry_form(group, "2026-01-07", "2"), **filters})
    assert response.status_code == 302
    location = response.headers["Location"]
    # The new entry may be on another page, so the list returns to page 1.
    assert "q=alpha" in location and "sort=-note" in location and "page=" not in location


def test_entries_csv_takes_the_search(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="first batch"))
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-21", "6", note="second batch"))
    lines = client.get(entry_url(tracker, ".csv?q=SECOND")).get_data(as_text=True).splitlines()
    assert len(lines) == 2 and lines[1].endswith(",second batch")


def test_risk_register_matches_the_report_order(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    for ref, rag, status, target in (
        ("R1", "Green", "Open", None),
        ("R2", "Red", "Open", None),
        ("R3", "Red", "In progress", date(2020, 1, 3)),
        ("R4", None, "Open", None),
        ("R5", "Amber", "Closed", None),
    ):
        db.add(
            Risk(tracker_id=tracker.id, ref=ref, description=f"Risk {ref}", rag=rag, status=status, target_date=target)
        )
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/risks").get_data(as_text=True)
    register, closed = html.split("Closed risks (1)")
    order = [ref for ref in ("R1", "R2", "R3", "R4") if f'risk-ref" data-label="">{ref}<' in register]
    assert sorted(order, key=register.index) == ["R3", "R2", "R1", "R4"]
    assert 'risk-ref" data-label="">R5<' in closed and 'risk-ref" data-label="">R5<' not in register
    assert "days overdue" in register
    red_chip = html[html.index('data-status="red"') :]
    assert 'Red <span class="chip-count" data-count>2</span>' in red_chip[: red_chip.index("</button>")]
    assert 'data-status="overdue"' in html and "Past target date" in html
    assert 'data-status="red overdue"' in register and 'data-sort-rag="0"' in register
    assert 'data-sort-rag="3"' in register and 'id="risks-table"' in register
    assert 'id="closed-risks-table"' in closed and 'data-state-prefix="closed-"' in closed
    assert "Showing 4 of 4 risks" in register
    assert "risks.js" not in html and "data-risk-rows" not in html
    assert "tabulator" not in html


def test_risk_form_previews_the_report_row(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="Existing"))
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/risks/new").get_data(as_text=True)
    assert 'placeholder="R2"' in html and "<strong data-preview-ref>R2</strong>" in html
    assert 'type="radio" name="status" value="Open" checked' in html
    assert 'type="radio" name="rag" value="" checked' in html
    response = post(
        client,
        f"/trackers/{tracker.id}/risks",
        {"description": "Supplier delay", "status": "In progress", "rag": "Amber"},
    )
    assert response.status_code == 302
    risk = db.scalars(select(Risk).where(Risk.ref == "R2")).one()
    assert (risk.status, risk.rag) == ("In progress", "Amber")


def test_targets_saved_per_week(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 9, 4), target=3, imported_actual=9))
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 9, 11), target=4))
    db.commit()
    response = post(
        client,
        f"/trackers/{tracker.id}/targets",
        {"target-2026-09-04": "10", "target-2026-09-11": "", "target-2026-09-18": "0"},
    )
    assert response.status_code == 302
    db.expire_all()
    rows = {w.week_ending: w for w in db.scalars(select(Week))}
    assert rows[date(2026, 9, 4)].target == 10 and rows[date(2026, 9, 4)].imported_actual == 9
    assert rows[date(2026, 9, 11)].target is None
    assert rows[date(2026, 9, 18)].target == 0


def test_target_notes_are_saved_with_the_targets(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 9, 4), target=3, note="Old note"))
    db.commit()
    response = post(
        client,
        f"/trackers/{tracker.id}/targets",
        {"target-2026-09-04": "3", "note-2026-09-04": "", "note-2026-09-11": " Bank holiday on Monday "},
    )
    assert response.status_code == 302
    db.expire_all()
    rows = {w.week_ending: w for w in db.scalars(select(Week))}
    assert rows[date(2026, 9, 4)].note == "" and rows[date(2026, 9, 4)].target == 3
    # A week with a note and no target still gets a row, so the note is kept.
    assert (rows[date(2026, 9, 11)].note, rows[date(2026, 9, 11)].target) == ("Bank holiday on Monday", None)
    log = db.scalars(select(AuditLog).where(AuditLog.action == "targets_updated")).one()
    assert log.detail["2026-09-04 note"] == ["Old note", ""]
    assert log.detail["2026-09-11 note"] == ["", "Bank holiday on Monday"]
    assert "2026-09-04" not in log.detail


def test_targets_page_shows_each_note_under_its_week(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Week(tracker_id=tracker.id, week_ending=date(2026, 9, 4), target=3, note="Two extra engineers"))
    db.commit()
    page = client.get(f"/trackers/{tracker.id}/targets").get_data(as_text=True)
    assert '<span class="target-note-preview" data-note-preview>Two extra engineers</span>' in page
    assert re.search(r'<textarea id="note-2026-09-04" name="note-2026-09-04"[^>]*>Two extra engineers</textarea>', page)
    assert 'aria-label="Edit the note for the week ending 04 Sep 2026"' in page
    assert 'aria-label="Add a note for the week ending 11 Sep 2026"' in page
    assert page.count('<tr class="target-note-row"') == page.count("data-note-toggle")


def test_a_note_that_is_too_long_saves_nothing_and_stays_open(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, f"/trackers/{tracker.id}/targets", {"target-2026-09-04": "5", "note-2026-09-04": "x" * 501})
    assert response.status_code == 400
    assert db.scalars(select(Week)).all() == []
    page = response.get_data(as_text=True)
    assert "is 501 characters long. The most is 500." in page
    assert re.search(r'<tr class="target-note-row" id="note-row-2026-09-04" data-note-row>', page)


def test_targets_invalid_value_changes_nothing(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, f"/trackers/{tracker.id}/targets", {"target-2026-09-04": "-1"})
    assert response.status_code == 400
    assert db.scalars(select(Week)).all() == []


def test_inputs_record_prepared_by(client, db, tracker_factory, user_factory, grant):
    tracker, user, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/inputs?week=2026-10-16"
    assert post(client, url, {"status": "Amber", "headline": "On course", "decisions": "None"}).status_code == 302
    row = db.get(ReportInput, (tracker.id, date(2026, 10, 16)))
    assert (row.status, row.headline, row.prepared_by) == ("Amber", "On course", user.id)
    first_stamp = row.updated_at
    post(client, url, {"status": "", "headline": "Revised"})
    db.expire_all()
    row = db.get(ReportInput, (tracker.id, date(2026, 10, 16)))
    assert row.status is None and row.headline == "Revised" and row.updated_at > first_stamp


def test_targets_page_summarises_the_plan(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add_all(
        [
            Week(tracker_id=tracker.id, week_ending=date(2026, 9, 4), target=10),
            Week(tracker_id=tracker.id, week_ending=date(2026, 9, 11), target=15),
        ]
    )
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/targets").get_data(as_text=True)
    scope = group.baseline
    assert '<span data-stat="planned">25</span>' in html
    assert f"{scope - 25} devices not yet planned" in html
    assert 'data-week="2026-09-04"' in html and "targets.js" in html


def test_inputs_page_shows_the_week_figures_and_previous_week(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(ReportInput(tracker_id=tracker.id, week_ending=date(2026, 10, 9), status="Green", headline="Good week"))
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="d", rag="Red", target_date=date(2026, 10, 1)))
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True)
    assert "Nobody has written this week up yet." not in html
    assert "data-copy-last hidden" in html and 'data-headline="Good week"' in html
    assert f'href="/trackers/{tracker.id}/inputs?week=2026-10-09" rel="prev"' in html
    # The figures are tiles under the week bar; the old panel is gone.
    assert "This week's figures" not in html and "figure-grid" not in html
    page = unescape(html)
    assert page.count('class="access-tile"') == 6 and 'class="access-tiles"' in page
    for label in ("Done this week", "Completed", "Rate (3 weeks)", "Forecast", "Next week's target", "Red risks"):
        assert f'<span class="access-tile-label">{label}</span>' in page
    assert "Week ending 23 Oct" in page
    assert "1 past its target date" in page
    assert f'href="/trackers/{tracker.id}/risks"' in page


def test_inputs_page_week_bar(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(ReportInput(tracker_id=tracker.id, week_ending=date(2026, 10, 16), status="Amber", headline="Slow"))
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True)
    bar = html[html.index('class="week-bar') : html.index("access-tiles")]
    assert 'aria-controls="week-strip-panel"' in bar and "aria-expanded=" in bar
    assert "Week ending 16 Oct 2026" in bar
    assert "Written \u00b7 Amber" in bar
    assert "Automatic sending is off" in bar
    assert "Latest week" in bar and 'rel="prev"' in bar and 'rel="next"' in bar
    assert 'id="week-strip-panel"' in html and "data-week-strip" in html
    # Not the week bar's old header copy.
    assert "This week is still in progress." not in html


def test_inputs_page_week_bar_deadline_follows_the_send(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client, schedule_enabled=True)
    url = f"/trackers/{tracker.id}/inputs?week=2026-10-23"
    # 16:02 UTC on 23 Oct 2026 is 17:02 in London (summer time).
    db.add(
        ReportSend(
            tracker_id=tracker.id,
            week_ending=date(2026, 10, 23),
            trigger="manual",
            status="failed",
            recipients=[],
            sent_at=datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc),
        )
    )
    db.add(
        ReportSend(
            tracker_id=tracker.id,
            week_ending=date(2026, 10, 23),
            trigger="scheduled",
            status="sent",
            recipients=[],
            sent_at=datetime(2026, 10, 23, 16, 2, tzinfo=timezone.utc),
        )
    )
    db.commit()
    assert "Report sent on Fri 23 Oct at 17:02" in client.get(url).get_data(as_text=True)
    # A week with nothing sent and its send time long gone.
    assert "Report was due on Fri 16 Oct at 17:00" in client.get(url.replace("23", "16")).get_data(as_text=True)


def test_inputs_page_week_bar_ignores_a_manual_send(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client, schedule_enabled=True)
    db.add(
        ReportSend(
            tracker_id=tracker.id,
            week_ending=date(2026, 10, 23),
            trigger="manual",
            status="sent",
            recipients=[],
            sent_at=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-23").get_data(as_text=True)
    assert "Report sent on" not in html and "Report was due on Fri 23 Oct at 17:00" in html


def test_inputs_page_cards(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True)
    assert html.count('class="access-card-head"') == 3
    commentary, reminder, _past = html.split('class="access-card-head"')[1:]
    assert "Commentary" in commentary[:200] and "Calendar reminder" in reminder[:200]
    # The preview sits inside the Commentary card; the Save bar comes last on the page, after Past updates, and its
    # button names the form it saves.
    assert "data-band" in commentary and "settings-actions" not in commentary
    assert html.index('class="settings-section past-updates"') < html.index('class="settings-actions"')
    assert 'type="submit" form="inputs-form">Save</button>' in html and 'id="inputs-form"' in html
    assert "Preview: top of the report" in commentary
    assert "Use last week" not in html or html.index("Use last week") < html.index("data-band")


def past_rows(html):
    table = html[html.index('id="past-updates"') :]
    table = table[: table.index("</table>")]
    return re.findall(r"<tr data-status.*?</tr>", table, re.S)


def test_past_updates_table(client, db, tracker_factory, user_factory, grant):
    tracker, user, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add_all(
        [
            ReportInput(
                tracker_id=tracker.id,
                week_ending=date(2026, 9, 4),
                status="Green",
                headline="On plan",
                decisions="",
                prepared_by=user.id,
            ),
            ReportInput(
                tracker_id=tracker.id, week_ending=date(2026, 9, 11), status="Red", headline="Late", decisions="Staff"
            ),
            ReportInput(tracker_id=tracker.id, week_ending=date(2026, 9, 18), status=None, headline="No status yet"),
        ]
    )
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-02").get_data(as_text=True)
    assert "Past updates" in html and "Each week's commentary as the report showed it." in html
    assert '<span class="count-pill">4' in html
    assert 'id="past-updates"' in html and 'data-state-prefix="past-"' in html
    assert "Search updates" in html and "lists.js" in html
    for label in ("Week ending", "Status", "Headline", "Needed from you", "Prepared by"):
        assert label in html[html.index('id="past-updates"') :]
    rows = past_rows(html)
    # Newest first, so the week before the shown one leads.
    assert [re.search(r'data-sort-week="([\d-]+)"', r).group(1) for r in rows] == [
        "2026-09-25",
        "2026-09-18",
        "2026-09-11",
        "2026-09-04",
    ]
    unwritten, nostatus, red, green = rows
    assert 'data-status="unwritten"' in unwritten and "Not written" in unwritten
    assert unwritten.count(">\u2013</td>") == 3 and "None" not in unwritten
    assert 'data-status="nostatus"' in nostatus and "Status not set" in nostatus and "No status yet" in nostatus
    assert 'data-status="red"' in red and "rag-dot-red" in red and "Staff" in red
    assert 'data-status="green"' in green and "None" in green and user.full_name in green
    assert f'href="/trackers/{tracker.id}/inputs?week=2026-09-04"' in green
    # Counts: All 4, Green 1, Amber 0, Red 1, Not written 1 (the week without a status counts only in All).
    chips = re.findall(r'data-status="(\w+)" aria-pressed="\w+">([^<]+) <span class="chip-count[^>]*>(\d+)', html)
    assert [(c[1].strip(), c[2]) for c in chips if c[0] in ("all", "green", "amber", "red", "unwritten")][:5] == [
        ("All", "4"),
        ("Green", "1"),
        ("Amber", "0"),
        ("Red", "1"),
        ("Not written", "1"),
    ]
    assert "Showing 4 of 4 weeks" in html


def test_past_updates_first_week_has_no_table(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-09-04").get_data(as_text=True)
    assert "Past updates" in html and "No earlier weeks yet." in html
    assert 'id="past-updates"' not in html


def test_inputs_week_outside_tracker_is_404(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    assert client.get(f"/trackers/{tracker.id}/inputs?week=2030-01-04").status_code == 404


def test_risk_ref_autonumbered(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/risks"
    post(client, url, {"description": "Supply delay", "group_id": str(group.id), "rag": "Red"})
    post(client, url, {"description": "Access", "status": "In progress"})
    refs = [r.ref for r in db.scalars(select(Risk).order_by(Risk.id))]
    assert refs == ["R1", "R2"]


def test_risk_edit_and_validation(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/risks"
    post(client, url, {"description": "Supply delay"})
    risk = db.scalars(select(Risk)).one()
    assert post(client, f"{url}/{risk.id}", {"description": "Supply delay", "status": "Done"}).status_code == 400
    assert (
        post(
            client, f"{url}/{risk.id}", {"description": "x", "status": "Closed", "rag": "Green", "group_id": "999"}
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            f"{url}/{risk.id}",
            {"description": "Updated", "status": "Closed", "rag": "Green", "group_id": str(group.id)},
        ).status_code
        == 302
    )
    db.expire_all()
    risk = db.get(Risk, risk.id)
    assert (risk.description, risk.status, risk.rag, risk.group_id) == ("Updated", "Closed", "Green", group.id)
    assert client.get(f"{url}/{risk.id}").status_code == 200


def test_risk_register_links_to_add_edit_and_delete(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/risks"
    post(client, url, {"description": "Supply delay"})
    risk = db.scalars(select(Risk)).one()
    html = client.get(url).get_data(as_text=True)
    assert f'href="{url}/new"' in html
    assert f'href="{url}/{risk.id}"' in html
    assert f'action="{url}/{risk.id}/delete"' in html and "data-confirm=" in html
    assert 'name="description"' not in html  # the form has its own page
    new_page = client.get(f"{url}/new")
    assert new_page.status_code == 200 and b'name="description"' in new_page.data
    assert re.search(
        rb'aria-current="page"><svg[^>]*>.*?</svg>Risks<', new_page.data, re.S
    )  # the Risks tab, after its icon


def test_risk_form_errors_render_on_the_form_page(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    response = post(client, f"/trackers/{tracker.id}/risks", {"description": "x", "status": "Done"})
    assert response.status_code == 400
    assert b"Please correct the following" in response.data and b'name="description"' in response.data


def test_risk_delete(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/risks"
    post(client, url, {"description": "Supply delay"})
    risk_id = db.scalars(select(Risk.id)).one()
    assert post(client, f"{url}/{risk_id}/delete").status_code == 302
    db.expire_all()
    assert db.scalars(select(Risk)).all() == []
    deleted = db.scalars(select(AuditLog).where(AuditLog.action == "risk_deleted")).one()
    assert deleted.detail == {"ref": "R1", "description": "Supply delay"}
    assert post(client, f"{url}/{risk_id}/delete").status_code == 404


def test_risk_delete_needs_editor_and_same_tracker(client, db, tracker_factory, user_factory, grant):
    tracker, user, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = tracker_factory(name="Other")
    risk = Risk(tracker_id=tracker.id, ref="R1")
    elsewhere = Risk(tracker_id=other.id, ref="R1")
    db.add_all([risk, elsewhere])
    db.commit()
    assert post(client, f"/trackers/{tracker.id}/risks/{elsewhere.id}/delete").status_code == 404
    db.get(TrackerRole, (user.id, tracker.id)).role = "viewer"
    db.commit()
    assert post(client, f"/trackers/{tracker.id}/risks/{risk.id}/delete").status_code == 404
    db.expire_all()
    assert len(db.scalars(select(Risk)).all()) == 2


def test_duplicate_risk_ref_rejected(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    url = f"/trackers/{tracker.id}/risks"
    post(client, url, {"ref": "X1", "description": "a"})
    assert post(client, url, {"ref": "X1", "description": "b"}).status_code == 400


def test_viewer_cannot_post_entry(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client, role="viewer")
    assert post(client, entry_url(tracker, "/new"), entry_form(group)).status_code == 404
    assert client.get(entry_url(tracker)).status_code == 404
    assert post(client, f"/trackers/{tracker.id}/targets", {}).status_code == 404
    assert post(client, f"/trackers/{tracker.id}/inputs", {}).status_code == 404
    assert post(client, f"/trackers/{tracker.id}/risks", {}).status_code == 404


def test_nav_links_shown_to_editor_only(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    assert b"Weekly update" in client.get(f"/trackers/{tracker.id}/groups").data


def test_archived_tracker_refuses_every_post(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client, status="archived")
    entry = CompletionEntry(
        tracker_id=tracker.id,
        group_id=group.id,
        entry_date=date(2026, 10, 14),
        week_ending=date(2026, 10, 16),
        quantity=2,
    )
    risk = Risk(tracker_id=tracker.id, ref="R1")
    db.add_all([entry, risk])
    db.commit()
    base = f"/trackers/{tracker.id}"
    posts = [
        (f"{base}/entries/new", entry_form(group)),
        (f"{base}/entries/{entry.id}/delete", {}),
        (f"{base}/targets", {"target-2026-09-04": "5"}),
        (f"{base}/inputs?week=2026-10-16", {"headline": "x"}),
        (f"{base}/risks", {"description": "x"}),
        (f"{base}/risks/{risk.id}", {"description": "x"}),
        (f"{base}/risks/{risk.id}/delete", {}),
    ]
    for url, data in posts:
        response = post(client, url, data, follow_redirects=True)
        assert b"This tracker is archived." in response.data, url
    db.expire_all()
    assert db.scalars(select(CompletionEntry)).all() == [entry]
    assert db.scalars(select(Week)).all() == []
    assert db.scalars(select(ReportInput)).all() == []
    assert db.scalars(select(Risk)).all() == [risk]


# --- Correcting an entry in place ----------------------------------------------------------------------------


def edit_url(tracker, entry):
    return f"/trackers/{tracker.id}/entries/{entry.id}/edit"


def make_entry(
    db, tracker, group, entry_date=date(2026, 10, 14), week_ending=date(2026, 10, 16), quantity=12, note="n"
):
    entry = CompletionEntry(
        tracker_id=tracker.id,
        group_id=group.id,
        entry_date=entry_date,
        week_ending=week_ending,
        quantity=quantity,
        note=note,
    )
    db.add(entry)
    db.commit()
    return entry


def test_editors_and_owners_can_edit_and_viewers_cannot(
    client, db, tracker_factory, user_factory, grant, team_factory, add_member
):
    from tests.conftest import sign_in

    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    assert client.get(edit_url(tracker, entry)).status_code == 200
    owner = user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    assert client.get(edit_url(tracker, entry)).status_code == 200
    team = team_factory()
    tracker.team_id = team.id
    member = user_factory()
    add_member(team, member, "editor")
    db.commit()
    sign_in(client, member)
    assert client.get(edit_url(tracker, entry)).status_code == 200
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    sign_in(client, viewer)
    assert client.get(edit_url(tracker, entry)).status_code == 404
    assert post(client, edit_url(tracker, entry), entry_form(group, quantity="99")).status_code == 404
    db.expire_all()
    assert entry.quantity == 12


def test_edit_changes_fields_and_recalculates_the_week(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=10)
    db.add(other)
    db.commit()
    entry = make_entry(db, tracker, group)
    response = post(client, edit_url(tracker, entry), entry_form(other, "2026-10-20", "7", " moved "))
    assert response.status_code == 302
    db.expire_all()
    assert (entry.group_id, entry.entry_date, entry.week_ending, entry.quantity, entry.note) == (
        other.id,
        date(2026, 10, 20),
        date(2026, 10, 23),
        7,
        "moved",
    )


def test_edit_checks_like_a_new_entry(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = post(client, edit_url(tracker, entry), entry_form(group, tomorrow))
    assert response.status_code == 400 and "The date cannot be after today" in response.get_data(as_text=True)
    response = post(client, edit_url(tracker, entry), entry_form(group, "2026-01-05"))
    assert response.status_code == 400 and OUTSIDE in response.get_data(as_text=True)
    for bad in ("0", "abc"):
        assert post(client, edit_url(tracker, entry), entry_form(group, quantity=bad)).status_code == 400
    db.expire_all()
    assert (entry.entry_date, entry.quantity) == (date(2026, 10, 14), 12)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all() == []


def test_a_retired_location_can_be_kept_but_not_chosen(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=10, retired=True)
    foreign_tracker = tracker_factory(name="Other")
    foreign = Group(tracker_id=foreign_tracker.id, name="Elsewhere", baseline=1)
    db.add_all([other, foreign])
    db.commit()
    entry = make_entry(db, tracker, group)
    group.retired = True
    db.commit()
    page = client.get(edit_url(tracker, entry)).get_data(as_text=True)
    assert "Site A (retired)" in page and "Site B" not in page
    assert post(client, edit_url(tracker, entry), entry_form(group, quantity="13")).status_code == 302
    response = post(client, edit_url(tracker, entry), entry_form(other))
    assert response.status_code == 400 and "Entries cannot be moved to a retired group." in response.get_data(
        as_text=True
    )
    response = post(client, edit_url(tracker, entry), entry_form(foreign))
    assert response.status_code == 400 and "Choose a group." in response.get_data(as_text=True)
    db.expire_all()
    assert (entry.group_id, entry.quantity) == (group.id, 13)


def test_edit_refused_on_an_archived_tracker(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client, status="archived")
    entry = make_entry(db, tracker, group)
    for response in (
        client.get(edit_url(tracker, entry), follow_redirects=True),
        post(client, edit_url(tracker, entry), entry_form(group, quantity="99"), follow_redirects=True),
    ):
        assert b"This tracker is archived." in response.data
    db.expire_all()
    assert entry.quantity == 12


def test_edit_logs_one_entry_updated_with_changed_fields_only(client, db, tracker_factory, user_factory, grant):
    tracker, user, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group, note="")
    post(client, edit_url(tracker, entry), entry_form(group, quantity="15", note=""))
    (logged,) = db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all()
    assert logged.detail == {
        "entry_date": entry.entry_date.isoformat(),
        "group": group.name,
        "before": {"quantity": 12},
        "after": {"quantity": 15},
    }
    assert logged.user_id == user.id
    assert logged.entity == "entry" and logged.entity_id == str(entry.id) and logged.tracker_id == tracker.id


def test_edit_logs_the_location_name_when_it_changes(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    other = Group(tracker_id=tracker.id, name="Site B", baseline=10)
    db.add(other)
    db.commit()
    entry = make_entry(db, tracker, group)
    post(client, edit_url(tracker, entry), entry_form(other, quantity="12", note="n"))
    (logged,) = db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all()
    assert logged.detail == {
        "entry_date": "2026-10-14",
        "group": "Site B",
        "before": {"group_id": group.id, "group": "Site A"},
        "after": {"group_id": other.id, "group": "Site B"},
    }


def test_saving_without_changes_writes_no_entry(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    response = post(client, edit_url(tracker, entry), entry_form(group, quantity="12", note="n"), follow_redirects=True)
    assert b"No changes to save." in response.data
    assert db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all() == []


def test_report_figures_follow_the_corrected_entry(client, db, tracker_factory, user_factory, grant):
    from tracker.report.build import compute_position

    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    args = (db, tracker, date(2026, 10, 16), date(2026, 10, 30))
    before = compute_position(*args).headline.completed
    post(client, edit_url(tracker, entry), entry_form(group, quantity="15", note="n"))
    db.expire_all()
    assert compute_position(*args).headline.completed == before + 3


def test_editing_a_deleted_or_foreign_entry_is_404(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    foreign_tracker = tracker_factory(name="Other")
    foreign_group = Group(tracker_id=foreign_tracker.id, name="Elsewhere", baseline=1)
    db.add(foreign_group)
    db.commit()
    foreign = make_entry(db, foreign_tracker, foreign_group)
    assert client.get(edit_url(tracker, foreign)).status_code == 404
    assert post(client, edit_url(tracker, foreign), entry_form(group)).status_code == 404
    url = edit_url(tracker, entry)
    db.delete(entry)
    db.commit()
    assert client.get(url).status_code == 404
    assert post(client, url, entry_form(group, quantity="99")).status_code == 404
    assert db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all() == []


def test_entries_page_offers_edit_and_drops_the_delete_and_record_note(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    page = client.get(entry_url(tracker)).get_data(as_text=True)
    assert f'href="{edit_url(tracker, entry)}"' in page
    assert "Edit 12 for Site A on" in page
    assert "delete it and record it again" not in page
    assert "Use Edit to correct an entry; delete only entries recorded by mistake." in page


def test_edit_refuses_a_missing_or_garbled_date_and_out_of_range_values(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    entry = make_entry(db, tracker, group)
    url = edit_url(tracker, entry)
    for bad_date in ("", "garbage", "2026-13-45"):
        response = post(client, url, entry_form(group, bad_date))
        assert response.status_code == 400 and "Enter a valid date." in response.get_data(as_text=True)
    response = post(client, url, entry_form(group, "9999-12-31"))
    assert response.status_code == 400 and OUTSIDE in response.get_data(as_text=True)
    response = post(client, url, entry_form(group, quantity="99999999999"))
    assert response.status_code == 400 and "The quantity can be at most 2,147,483,647." in response.get_data(
        as_text=True
    )
    assert post(client, url, entry_form(group, quantity="9" * 5000)).status_code == 400
    assert post(client, url, {**entry_form(group), "group_id": "9" * 5000}).status_code == 400
    db.expire_all()
    assert (entry.entry_date, entry.quantity) == (date(2026, 10, 14), 12)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "entry_updated")).all() == []


def test_new_entry_refuses_out_of_range_values_like_edit(client, db, tracker_factory, user_factory, grant):
    sundays = {"week_ending_weekday": 6, "first_week_ending": date(2026, 9, 6), "last_week_ending": date(2026, 12, 27)}
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client, **sundays)
    url = entry_url(tracker, "/new")
    response = post(client, url, entry_form(group, "9999-12-31"))  # its week would end in year 10000
    assert response.status_code == 400 and "That date is outside this tracker" in response.get_data(as_text=True)
    response = post(client, url, entry_form(group, quantity="2147483648"))
    assert response.status_code == 400 and "The quantity can be at most 2,147,483,647." in response.get_data(
        as_text=True
    )
    assert post(client, url, {**entry_form(group), "group_id": str(2**31)}).status_code == 400
    assert db.scalars(select(CompletionEntry)).first() is None


def test_entries_ignore_a_location_id_that_cannot_exist(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-14", "5", note="at A"))
    for big in ("9" * 20, "9" * 5000):
        page = client.get(entry_url(tracker) + f"?group={big}")
        assert page.status_code == 200 and "at A" in page.get_data(as_text=True)
        csv_page = client.get(entry_url(tracker, f".csv?group={big}"))
        assert csv_page.status_code == 200 and len(csv_page.get_data(as_text=True).splitlines()) == 2


def test_past_updates_list_only_weeks_that_have_started(client, db, tracker_factory, user_factory, grant):
    from tracker.engine.weeks import in_progress_week, week_endings

    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    started = in_progress_week(date.today(), tracker.week_ending_weekday)
    html = client.get(f"/trackers/{tracker.id}/inputs?week={weeks[-1].isoformat()}").get_data(as_text=True)
    listed = [re.search(r'data-sort-week="([\d-]+)"', r).group(1) for r in past_rows(html)]
    expected = [w.isoformat() for w in reversed(weeks[:-1]) if w <= (started or date.today())]
    assert listed == expected and len(listed) < len(weeks) - 1
    assert f'<span class="count-pill">{len(expected)}' in html
    assert f"Showing {len(expected)} of {len(expected)} weeks" in html


def test_weekly_update_opens_on_the_week_ending_day(client, db, tracker_factory, user_factory, grant, monkeypatch):
    """On the week-ending day no week is in progress; the page used to fail comparing a date with None."""
    from tracker.engine.weeks import week_endings
    from tracker.entries import views

    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    ending_day = weeks[2]

    class OnTheWeekEndingDay(date):
        @classmethod
        def today(cls):
            return ending_day

    monkeypatch.setattr(views, "date", OnTheWeekEndingDay)
    response = client.get(f"/trackers/{tracker.id}/inputs?week={weeks[-1].isoformat()}")
    assert response.status_code == 200
    listed = [re.search(r'data-sort-week="([\d-]+)"', r).group(1) for r in past_rows(response.get_data(as_text=True))]
    assert listed == [w.isoformat() for w in reversed(weeks[:3])]  # the week ending today is listed


def test_red_risks_tile_counts_only_red_risks_past_their_target_date(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="d", rag="Red", target_date=date(2026, 12, 20)))
    db.add(Risk(tracker_id=tracker.id, ref="R2", description="d", rag="Amber", target_date=date(2026, 10, 1)))
    db.commit()
    page = unescape(client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True))
    assert "None past their target date" in page and "past its target date" not in page


def test_the_rate_tile_without_a_required_rate(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client, target_completion=None)
    page = unescape(client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True))
    assert "a week · no required rate" in page and "– needed" not in page


def test_the_disabled_week_steps_use_screen_reader_text(client, db, tracker_factory, user_factory, grant):
    tracker, _, _ = setup_editor(db, tracker_factory, user_factory, grant, client)
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-09-04").get_data(as_text=True)
    assert re.search(r'is-disabled" aria-disabled="true">.*?<span class="sr-only">Previous week</span>', html, re.S)
    assert 'aria-disabled="true" aria-label' not in html


def test_only_the_red_risks_tile_takes_the_hover_border():
    css = (Path(__file__).parent.parent / "tracker" / "static" / "tracker.css").read_text()
    assert ".inputs-page div.access-tile:hover { border-color: var(--border); }" in css


def test_past_updates_name_a_missing_preparer_as_a_former_user(db, tracker_factory):
    from tracker.entries.views import _past_updates

    tracker = tracker_factory()
    week = date(2026, 9, 4)
    saved = {
        week: ReportInput(tracker_id=tracker.id, week_ending=week, status="Green", headline="h", prepared_by=999999)
    }
    [row] = _past_updates(db, [week], saved)
    assert row["prepared_by"] == "a former user"


def add_entries(db, tracker, rows):
    """``rows`` is (group, days before the week ending 2026-01-09, quantity, note)."""
    for group, days, quantity, note in rows:
        db.add(
            CompletionEntry(
                tracker_id=tracker.id,
                group_id=group.id,
                entry_date=date(2026, 1, 9) - timedelta(days=days),
                week_ending=date(2026, 1, 9),
                quantity=quantity,
                note=note,
            )
        )
    db.commit()


def positions(html: str, *needles: str) -> list[int]:
    return [html.index(needle) for needle in needles]


def test_rows_equal_on_the_sorted_column_keep_the_newest_first_order(client, db, tracker_factory, user_factory, grant):
    tracker, _, site_a = long_tracker(db, tracker_factory, user_factory, grant, client)
    alpha = Group(tracker_id=tracker.id, name="Alpha site", baseline=1)
    db.add(alpha)
    db.commit()
    add_entries(
        db,
        tracker,
        [
            (site_a, 3, 1, "beta old"),
            (site_a, 0, 1, "beta new"),
            (alpha, 4, 1, "alpha old"),
            (alpha, 1, 1, "alpha new"),
        ],
    )
    default_order = ("beta new", "alpha new", "beta old", "alpha old")  # newest date first
    for sort, expected in (
        ("location", ("alpha new", "alpha old", "beta new", "beta old")),
        ("-location", ("beta new", "beta old", "alpha new", "alpha old")),
        ("quantity", default_order),  # every quantity is equal, so each row keeps the default order
        ("-quantity", default_order),
    ):
        html = client.get(entry_url(tracker, f"?sort={sort}")).get_data(as_text=True)
        order = positions(html, *expected)
        assert order == sorted(order), sort


def test_location_and_note_sort_ignore_case_and_read_numbers_naturally(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, site_a = long_tracker(db, tracker_factory, user_factory, grant, client)
    ld5, ld10 = (
        Group(tracker_id=tracker.id, name="LD5", baseline=1),
        Group(tracker_id=tracker.id, name="ld10", baseline=1),
    )
    db.add_all([ld5, ld10])
    db.commit()
    add_entries(db, tracker, [(ld10, 0, 1, "Item 10"), (ld5, 1, 1, "item 5"), (site_a, 2, 1, "item 2")])
    html = client.get(entry_url(tracker, "?sort=location")).get_data(as_text=True)
    order = positions(html, 'Location">LD5<', 'Location">ld10<', 'Location">Site A<')
    assert order == sorted(order)
    html = client.get(entry_url(tracker, "?sort=-location")).get_data(as_text=True)
    order = positions(html, 'Location">Site A<', 'Location">ld10<', 'Location">LD5<')
    assert order == sorted(order)
    html = client.get(entry_url(tracker, "?sort=note")).get_data(as_text=True)
    order = positions(html, ">item 2<", ">item 5<", ">Item 10<")
    assert order == sorted(order)


def test_entries_with_no_note_come_last_in_both_directions(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    add_entries(db, tracker, [(group, 0, 1, ""), (group, 1, 2, "bravo"), (group, 2, 3, "alpha"), (group, 3, 4, "")])
    for sort, expected in (("note", [3, 2, 1, 4]), ("-note", [2, 3, 1, 4])):
        html = client.get(entry_url(tracker, f"?sort={sort}")).get_data(as_text=True)
        # The empty notes (quantities 1 and 4) follow the written ones, newest first.
        assert [int(n) for n in re.findall(r'class="num" data-label="Quantity">(\d)<', html)] == expected, sort


def test_entries_clear_filters_drops_search_location_and_week_and_keeps_the_sort(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 2, note="alpha")
    plain = client.get(entry_url(tracker)).get_data(as_text=True)
    assert "Clear filters" not in plain and "Clear search" not in plain
    keep = f"/trackers/{tracker.id}/entries?sort=-quantity"
    for query in (
        f"?sort=-quantity&q=alpha&group={group.id}&week=2026-01-02",
        "?sort=-quantity&q=alpha",
        f"?sort=-quantity&group={group.id}",
        "?sort=-quantity&week=2026-01-02",
    ):
        html = client.get(entry_url(tracker, query)).get_data(as_text=True)
        assert f'<a class="button button-small" href="{keep}">Clear filters</a>' in html, query
    assert "Clear search" not in html


def test_the_no_match_line_uses_the_table_look_and_offers_clear_filters(
    client, db, tracker_factory, user_factory, grant
):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 1, note="alpha")
    html = client.get(entry_url(tracker, "?q=nomatch&sort=note")).get_data(as_text=True)
    assert (
        f'<p class="list-no-match">No entries match these filters. '
        f'<a class="button button-small" href="/trackers/{tracker.id}/entries?sort=note">Clear filters</a></p>'
    ) in html
    html = client.get(entry_url(tracker, "?week=2025-12-26")).get_data(as_text=True)
    assert 'class="list-no-match"' in html


def test_the_pager_controls_that_cannot_be_used_are_plain_text(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = long_tracker(db, tracker_factory, user_factory, grant, client)
    weekly_entries(db, tracker, group, 12)
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert '<span class="pager-button is-disabled">Previous</span>' in html and "aria-disabled" not in html
