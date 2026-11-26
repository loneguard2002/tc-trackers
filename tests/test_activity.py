"""Activity screen (database required)."""

import html
import json
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from tests.conftest import post, sign_in
from tracker.activity.labels import ACTION_LABELS
from tracker.models import AuditLog

URL = "/admin/activity"


def text_of(response) -> str:
    return html.unescape(response.get_data(as_text=True))


def add(db, **kw) -> AuditLog:
    values = {"action": "login", "entity": "user", "entity_id": "1"}
    values.update(kw)
    row = AuditLog(**values)
    db.add(row)
    db.commit()
    return row


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=timezone.utc)


def test_activity_refused_without_view_activity(client, logged_in_user):
    assert client.get(URL).status_code == 403


def test_anonymous_goes_to_sign_in(client):
    assert client.get(URL).status_code in (302, 303)


def test_holder_and_admin_open_activity(client, logged_in_admin, user_factory, give_set):
    assert client.get(URL).status_code == 200
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    other = client.application.test_client()
    sign_in(other, holder)
    assert other.get(URL).status_code == 200


def ids_on(body: str) -> list[int]:
    return [int(n) for n in re.findall(r'<tr data-entry="(\d+)"', body)]


def fill(db, count: int) -> None:
    for n in range(count):
        add(db, at=at(1, 0).replace(minute=n % 60, hour=n // 60), action="entry_created", entity_id=str(n))


def test_newest_first_25_a_page_with_a_footer_and_page_links(client, logged_in_admin, db):
    fill(db, 120)
    first = text_of(client.get(URL))
    ids = ids_on(first)
    assert len(ids) == 25 and ids == sorted(ids, reverse=True)
    assert "Showing 1–25 of 120 entries" in first
    assert 'aria-label="Page 5"' in first and "page=2" in first and 'rel="next"' in first
    assert "Newer" not in first and "Older" not in first
    last = text_of(client.get(URL + "?page=5"))
    assert len(ids_on(last)) == 20
    assert "Showing 101–120 of 120 entries" in last
    assert 'rel="prev"' in last and 'rel="next"' not in last


def test_size_and_page_and_old_page_links(client, logged_in_admin, db):
    fill(db, 120)
    body = text_of(client.get(URL + "?size=50&page=2"))
    assert len(ids_on(body)) == 50 and "Showing 51–100 of 120 entries" in body
    assert 'name="size"' in body and '<option value="50" selected>' in body
    assert len(ids_on(text_of(client.get(URL + "?size=7")))) == 25
    old_link = text_of(client.get(URL + "?page=3"))  # an old bookmark: 50 a page then, 25 now
    assert "Showing 51–75 of 120 entries" in old_link
    past = text_of(client.get(URL + "?page=999"))
    assert "Showing 101–120 of 120 entries" in past and len(ids_on(past)) == 20


def test_short_list_footer_has_no_page_controls(client, logged_in_admin, db):
    fill(db, 3)
    body = text_of(client.get(URL))
    assert "Showing 1–3 of 3 entries" in body and "pager-controls" not in body


def names_in(body: str, column: int) -> list[str]:
    """The text of one column's cells, row by row (the page order)."""
    out = []
    for row in re.findall(r'<tr data-entry="\d+">(.*?)</tr>', body, re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        out.append(re.sub(r"<[^>]+>", " ", cells[column]).split()[0] if cells[column].strip() else "")
    return out


def test_sorting_each_key_both_ways(client, logged_in_admin, db, user_factory, tracker_factory):
    ann = user_factory(full_name="Ann Smith", email="ann@example.com")
    bob = user_factory(full_name="Bob Jones", email="bob@example.com")
    alpha, zulu = tracker_factory(name="Alpha"), tracker_factory(name="Zulu")
    one = add(db, at=at(1), user_id=bob.id, tracker_id=zulu.id, action="login")  # Signed in
    two = add(db, at=at(2), user_id=ann.id, tracker_id=alpha.id, action="user_created")  # User created
    three = add(db, at=at(3), user_id=None, tracker_id=None, action="entry_created")
    login_row = [r for r in (one, two, three)]
    assert ids_on(text_of(client.get(URL)))[:3] == [three.id, two.id, one.id]
    assert ids_on(text_of(client.get(URL + "?sort=time")))[:3] == [one.id, two.id, three.id]
    ann_bob = ids_on(text_of(client.get(URL + "?sort=actor")))
    assert ann_bob[:2] == [two.id, one.id]  # Ann, Bob (people without a name last)
    bob_ann = ids_on(text_of(client.get(URL + "?sort=-actor")))
    assert bob_ann[:2] == [one.id, two.id]
    assert ids_on(text_of(client.get(URL + "?sort=tracker")))[:2] == [two.id, one.id]
    assert ids_on(text_of(client.get(URL + "?sort=-tracker")))[:2] == [one.id, two.id]
    # Action sorts by its label: "Signed in" < "User created"; the other entry's label is whatever ACTION_LABELS says.
    labels = {r.id: ACTION_LABELS[r.action] for r in login_row}
    ordered = sorted(labels, key=lambda i: (labels[i].lower(), i))
    admin_rows = ids_on(text_of(client.get(URL + "?sort=action&size=100")))
    assert [i for i in admin_rows if i in labels] == ordered
    descending = ids_on(text_of(client.get(URL + "?sort=-action&size=100")))
    assert [i for i in descending if i in labels] == ordered[::-1]


def test_sort_links_and_aria_sort(client, logged_in_admin, db):
    add(db)
    body = text_of(client.get(URL))
    assert 'aria-sort="descending"' in body and body.count("aria-sort") == 4
    assert 'href="/admin/activity?sort=time"' in body  # a click on the sorted column reverses it
    assert 'href="/admin/activity?sort=actor"' in body
    flipped = text_of(client.get(URL + "?sort=actor"))
    assert 'href="/admin/activity?sort=-actor"' in flipped


def test_unlabelled_actions_sort_by_their_key(client, logged_in_admin, db):
    mystery = add(db, action="aaa_mystery", at=at(1))
    labelled = add(db, action="login", at=at(2))
    rows = ids_on(text_of(client.get(URL + "?sort=action")))
    assert rows.index(mystery.id) < rows.index(labelled.id)


def test_search_matches_names_emails_tracker_and_detail(client, logged_in_admin, db, user_factory, tracker_factory):
    actor = user_factory(full_name="Zanzibar Quill", email="zq.actor@example.com")
    target = user_factory(full_name="Wendeline Marsh", email="wm.target@example.org")
    tracker = tracker_factory(name="Orbital rollout")
    by_actor = add(db, user_id=actor.id)
    by_target = add(db, target_user_id=target.id)
    by_tracker = add(db, tracker_id=tracker.id, action="entry_created", detail={"quantity": 7})
    by_detail = add(db, action="team_created", detail={"name": "Kestrelwing"})
    unrelated = add(db)
    for q, wanted in [
        ("zanzibar", by_actor),
        ("ZQ.ACTOR@example", by_actor),
        ("wendeline", by_target),
        ("wm.target@example.org", by_target),
        ("orbital", by_tracker),
        ("kestrelwing", by_detail),
    ]:
        ids = ids_on(text_of(client.get(URL, query_string={"q": q})))
        assert ids == [wanted.id], q
    assert unrelated.id not in ids_on(text_of(client.get(URL, query_string={"q": "zanzibar"})))
    none = text_of(client.get(URL, query_string={"q": "no-such-text"}))
    assert ids_on(none) == [] and "No activity matches" in none and "Showing 0 of 0 entries" in none


def test_search_is_literal_for_wildcards_and_quotes(client, logged_in_admin, db):
    plain = add(db, action="team_created", detail={"name": "fifty percent"})
    literal = add(db, action="team_created", detail={"name": "50%_off \\ it's"})
    assert ids_on(text_of(client.get(URL, query_string={"q": "%"}))) == [literal.id]
    assert ids_on(text_of(client.get(URL, query_string={"q": "50%_off"}))) == [literal.id]
    assert ids_on(text_of(client.get(URL, query_string={"q": "_"}))) == [literal.id]
    assert ids_on(text_of(client.get(URL, query_string={"q": "it's"}))) == [literal.id]
    assert plain.id not in ids_on(text_of(client.get(URL, query_string={"q": "\\"})))
    assert client.get(URL, query_string={"q": "a\x00b"}).status_code < 500


def test_search_matches_detail_only_where_the_viewer_may_read_it(
    client, db, user_factory, give_set, tracker_factory, grant
):
    secret, shared = tracker_factory(name="Secret rollout"), tracker_factory(name="Shared rollout")
    hidden = add(db, tracker_id=secret.id, action="entry_created", detail={"note": "zirconium"})
    visible = add(db, tracker_id=shared.id, action="entry_created", detail={"note": "zirconium"})
    untracked = add(db, action="team_created", detail={"note": "zirconium"})
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    grant(holder, shared, "viewer")
    sign_in(client, holder)
    ids = ids_on(text_of(client.get(URL, query_string={"q": "zirconium"})))
    assert sorted(ids) == sorted([visible.id, untracked.id])  # not the entry about the tracker they cannot open
    # The tracker's name still matches, and the row still hides its detail.
    body = text_of(client.get(URL, query_string={"q": "Secret rollout"}))
    assert ids_on(body) == [hidden.id] and "zirconium" not in body and HIDDEN in body
    assert "Showing 1–1 of 1 entry" in body


def test_administrator_search_matches_every_detail(client, logged_in_admin, db, tracker_factory):
    secret = tracker_factory(name="Secret rollout")
    hidden = add(db, tracker_id=secret.id, action="entry_created", detail={"note": "zirconium"})
    assert ids_on(text_of(client.get(URL, query_string={"q": "zirconium"}))) == [hidden.id]


def test_filters_combine_with_q_and_stay_in_every_link(client, logged_in_admin, db, user_factory):
    a, b = user_factory(full_name="Ann Lee"), user_factory(full_name="Bea Lee")
    keep = add(db, user_id=a.id, action="login", at=at(11))
    add(db, user_id=b.id, action="login", at=at(11))  # another person
    add(db, user_id=a.id, action="entry_created", at=at(11))  # another action
    add(db, user_id=a.id, action="login", at=at(20))  # outside the dates
    query = {"person": a.id, "action": "login", "from": "2026-10-10", "to": "2026-10-12", "q": "lee"}
    body = text_of(client.get(URL, query_string=query))
    assert ids_on(body) == [keep.id]
    assert ids_on(text_of(client.get(URL, query_string={**query, "q": "nomatch"}))) == []
    link = re.search(r'href="(/admin/activity\?[^"]*sort=actor[^"]*)"', body)
    assert link
    for part in (f"person={a.id}", "action=login", "from=2026-10-10", "to=2026-10-12", "q=lee"):
        assert part in link.group(1)
    assert 'name="person"' in body and 'name="action"' in body
    assert '<input id="filter-q" type="search" name="q" value="lee"' in body and 'name="from"' in body


def test_page_links_and_size_form_carry_q_sort_and_filters(client, logged_in_admin, db):
    for n in range(60):
        add(db, action="entry_created", detail={"note": "entry"}, entity_id=str(n))
    body = text_of(client.get(URL, query_string={"q": "entry", "sort": "-actor", "action": "entry_created"}))
    assert "Showing 1–25 of 60 entries" in body
    page_link = re.search(r'href="([^"]*page=2[^"]*)"', body).group(1)
    for part in ("q=entry", "sort=-actor", "action=entry_created"):
        assert part in page_link
    assert '<input type="hidden" name="q" value="entry">' in body
    assert '<input type="hidden" name="sort" value="-actor">' in body
    assert '<input type="hidden" name="action" value="entry_created">' in body
    assert 'name="page"' not in body.split("pager-size-form")[1].split("</form>")[0]


def test_clear_filters_clears_q_and_shows_when_only_q_is_set(client, logged_in_admin, db):
    add(db)
    assert "Clear filters" not in text_of(client.get(URL))
    body = text_of(client.get(URL, query_string={"q": "login"}))
    assert re.search(r'<a class="button" href="/admin/activity">Clear filters</a>', body)


def test_cells_carry_data_labels_for_the_phone_cards(client, logged_in_admin, db):
    entry = add(db)
    body = text_of(client.get(URL))
    row = re.search(rf'<tr data-entry="{entry.id}">(.*?)</tr>', body, re.DOTALL).group(1)
    labels = re.findall(r'<td[^>]*data-label="([^"]*)"', row)
    assert labels == ["Time", "Performed by", "User affected", "Action", "Tracker", "Detail"]
    assert "card-rows" in body and "data-table-frame" in body


def test_person_filter_matches_who_acted_or_who_was_affected(client, logged_in_admin, db, user_factory):
    a, b, c = user_factory(), user_factory(), user_factory()
    acted = add(db, user_id=a.id, target_user_id=c.id)
    affected = add(db, user_id=b.id, target_user_id=a.id)
    other = add(db, user_id=b.id, target_user_id=c.id)
    body = text_of(client.get(f"{URL}?person={a.id}"))
    assert f'data-entry="{acted.id}"' in body and f'data-entry="{affected.id}"' in body
    assert f'data-entry="{other.id}"' not in body


def test_action_and_date_range_filters(client, logged_in_admin, db):
    early = add(db, at=at(10, 0), action="login")
    late = add(db, at=at(12, 23), action="login")
    edge = add(db, at=at(12, 23), action="entry_created")
    body = text_of(client.get(f"{URL}?action=login&from=2026-10-10&to=2026-10-12"))
    assert f'data-entry="{early.id}"' in body and f'data-entry="{late.id}"' in body  # "to" is inclusive
    assert f'data-entry="{edge.id}"' not in body
    body = text_of(client.get(f"{URL}?from=2026-10-11"))
    assert f'data-entry="{early.id}"' not in body and f'data-entry="{late.id}"' in body
    body = text_of(client.get(f"{URL}?to=2026-10-11"))
    assert f'data-entry="{early.id}"' in body and f'data-entry="{late.id}"' not in body


@pytest.mark.parametrize(
    "query",
    [
        "page=abc",
        "page=0",
        "page=-3",
        "page=99999999999999999999",
        "from=2026-13-45",
        "to=zzz",
        "to=9999-12-31",
        "from=0001-01-01",
        "person=xyz",
        "person=99999999999999999999",
        "action=<b>",
    ],
)
def test_malformed_filters_fall_back_to_the_full_list(client, logged_in_admin, db, query):
    add(db)
    response = client.get(f"{URL}?{query}")
    assert response.status_code == 200
    assert "<b>" not in response.get_data(as_text=True)


def test_rows_with_deleted_people_or_trackers_and_any_detail_shape_render(client, logged_in_admin, db):
    add(db, user_id=None, target_user_id=None, tracker_id=None, detail=None)
    add(db, action="role_set", detail={"role": [None, "viewer"]})
    add(db, action="mystery", detail={"weird": [1, 2, 3], "nested": {"a": None}})
    add(db, action="team_renamed", detail={"before": "A", "after": "B"})
    add(db, action="entry_updated", detail={"before": "x", "after": {"q": 1}})
    add(db, action="login", detail={"before": ["a"], "after": None})
    body = text_of(client.get(URL))
    assert "mystery" in body and "viewer" in body and "nested" in body
    assert "Team details changed" in body


def test_tracker_names_shown_to_a_view_activity_holder_without_access(
    client, db, user_factory, give_set, tracker_factory
):
    tracker = tracker_factory(name="Secret rollout")
    add(db, tracker_id=tracker.id)
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    sign_in(client, holder)
    assert client.get(f"/trackers/{tracker.id}").status_code == 404
    assert "Secret rollout" in text_of(client.get(URL))


def test_no_secrets_in_any_entry(client, logged_in_admin, user_factory, db):
    p1, p2, p3 = "Pass-One-1111", "Pass-Two-2222", "Pass-Three-3333"
    post(client, "/admin/users", {"email": "new@example.com", "full_name": "New Person", "password": p1})
    victim = user_factory()
    post(client, f"/admin/users/{victim.id}/password", {"password": p2, "password_confirm": p2})
    post(client, "/admin/smtp", {"smtp_host": "smtp.example.com", "smtp_port": "25", "smtp_password": "smtp-secret-9"})
    fresh = client.application.test_client()
    post(fresh, "/login", {"email": victim.email, "password": p3})
    failed = db.scalars(select(AuditLog).where(AuditLog.action == "login_failed")).all()
    assert len(failed) == 1
    blob = json.dumps([e.detail for e in db.scalars(select(AuditLog))])
    for secret in (p1, p2, p3, "smtp-secret-9", "$2b$", "password_hash", "smtp_password"):
        assert secret not in blob


# --- Names, not contents ----------------------------------------------------------------------------------------------

HIDDEN = "Details hidden: you cannot open this tracker."


def test_detail_hidden_from_a_holder_who_cannot_open_the_tracker(
    client, db, user_factory, give_set, tracker_factory, grant
):
    secret, shared = tracker_factory(name="Secret rollout"), tracker_factory(name="Shared rollout")
    add(db, tracker_id=secret.id, action="entry_created", detail={"quantity": 4242})
    add(db, tracker_id=shared.id, action="entry_created", detail={"quantity": 5151})
    add(db, action="team_created", detail={"name": "Teamwide"})
    holder = user_factory()
    give_set(["view_activity"], user=holder)
    grant(holder, shared, "viewer")
    sign_in(client, holder)
    page = text_of(client.get(URL))
    assert "Secret rollout" in page and "4242" not in page and page.count(HIDDEN) == 1
    assert "Shared rollout" in page and "5151" in page and "Teamwide" in page


def test_administrator_sees_every_detail(client, logged_in_admin, db, tracker_factory):
    secret = tracker_factory(name="Secret rollout")
    add(db, tracker_id=secret.id, action="entry_created", detail={"quantity": 4242})
    page = text_of(client.get(URL))
    assert "4242" in page and HIDDEN not in page


def test_a_very_long_person_filter_is_ignored(client, logged_in_admin, db):
    add(db)
    response = client.get(URL + "?person=" + "9" * 5000)
    assert response.status_code == 200 and text_of(response).count("<tr data-entry") == 1


# --- Emails beside names ----------------------------------------------------------------------------------------------


def cells_of(body: str, entry: AuditLog) -> list[str]:
    """The inner HTML of each cell in an entry's row: time, performed by, user affected, action, tracker, detail."""
    row = re.search(rf'<tr data-entry="{entry.id}">(.*?)</tr>', body, re.DOTALL)
    assert row, f"entry {entry.id} is not on the page"
    return re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.DOTALL)


def test_entries_show_the_email_under_each_name(client, logged_in_admin, db, user_factory):
    first = user_factory(full_name="Jordan Lee", email="jordan.first@example.com")
    second = user_factory(full_name="Jordan Lee", email="jordan.second@example.com")
    forward = add(db, user_id=first.id, target_user_id=second.id)
    backward = add(db, user_id=second.id, target_user_id=first.id)
    body = client.get(URL).get_data(as_text=True)
    first_email = '<span class="member-email">jordan.first@example.com</span>'
    second_email = '<span class="member-email">jordan.second@example.com</span>'
    performed, affected = cells_of(body, forward)[1:3]
    assert "Jordan Lee" in performed and first_email in performed and second_email not in performed
    assert "Jordan Lee" in affected and second_email in affected and first_email not in affected
    performed, affected = cells_of(body, backward)[1:3]
    assert second_email in performed and first_email not in performed
    assert first_email in affected and second_email not in affected


def test_a_deleted_person_shows_a_deleted_badge_and_stays_in_the_filter(client, logged_in_admin, db, user_factory):
    gone = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    kept = user_factory(full_name="Jordan Lee", email="jordan.kept@example.com")
    entry = add(db, user_id=gone.id, target_user_id=kept.id)
    body = client.get(URL).get_data(as_text=True)
    assert f'<option value="{gone.id}">Jordan Lee (jordan.lee@example.com) – deleted</option>' in body
    assert f'<option value="{kept.id}">Jordan Lee (jordan.kept@example.com)</option>' in body
    badge = '<span class="badge badge-muted">Deleted</span>'
    performed, affected = cells_of(body, entry)[1:3]
    assert "jordan.lee@example.com" in performed and badge in performed
    assert "jordan.kept@example.com" in affected and badge not in affected


def test_filtering_by_a_new_account_with_a_reused_email_shows_only_its_entries(
    client, logged_in_admin, db, user_factory
):
    old = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    new = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com")
    old_entry, new_entry = add(db, user_id=old.id), add(db, user_id=new.id)
    body = client.get(f"{URL}?person={new.id}").get_data(as_text=True)
    assert f'data-entry="{new_entry.id}"' in body and f'data-entry="{old_entry.id}"' not in body
    assert f'<option value="{new.id}" selected>Jordan Lee (jordan.lee@example.com)</option>' in body
    assert f'<option value="{old.id}">Jordan Lee (jordan.lee@example.com) – deleted</option>' in body


def test_entries_without_a_person_show_a_dash(client, logged_in_admin, db, user_factory):
    person = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com")
    nobody = add(db, user_id=None, target_user_id=None)
    only_affected = add(db, user_id=None, target_user_id=person.id)
    body = client.get(URL).get_data(as_text=True)
    assert [cell.strip() for cell in cells_of(body, nobody)[1:3]] == ["–", "–"]
    performed, affected = cells_of(body, only_affected)[1:3]
    assert performed.strip() == "–"
    assert "jordan.lee@example.com" in affected
