"""Data entry routes: completions, targets, weekly inputs, risks (database required)."""

from datetime import date

from sqlalchemy import select

from tests.conftest import post
from tracker.engine.calc import group_positions
from tracker.models import AuditLog, CompletionEntry, Group, ReportInput, Risk, TrackerRole, Week
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
    assert 'aria-current="true">All locations<span class="chip-count">2</span>' in html
    assert 'Site B<span class="chip-count">1</span>' in html
    html = client.get(entry_url(tracker) + f"?group={other.id}").get_data(as_text=True)
    assert "at B" in html and "at A" not in html
    assert "<strong>3</strong> recorded at Site B" in html


def test_quick_add_returns_to_the_entries_list(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert 'name="return_to" value="list"' in html and "data-quick-add" in html
    response = post(client, entry_url(tracker, "/new"), {**entry_form(group), "return_to": "list"})
    assert response.status_code == 302 and response.headers["Location"].endswith(entry_url(tracker))
    response = post(client, entry_url(tracker, "/new"), entry_form(group))
    assert response.headers["Location"].endswith(entry_url(tracker, f"/new?group={group.id}"))


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


def test_entries_list_says_when_it_is_capped(client, db, tracker_factory, user_factory, grant, monkeypatch):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    monkeypatch.setattr("tracker.entries.views.LIST_LIMIT", 2)
    for day in ("2026-10-14", "2026-10-15"):
        post(client, entry_url(tracker, "/new"), entry_form(group, day))
    assert "Showing the latest" not in client.get(entry_url(tracker)).get_data(as_text=True)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-16"))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert "Showing the latest 2 entries only." in html
    assert "Download CSV includes every matching entry." in html
    assert "Showing the latest 2 of 3 entries this week." in html  # the week total still counts all three


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
    order = [ref for ref in ("R1", "R2", "R3", "R4") if f'risk-ref">{ref}<' in register]
    assert sorted(order, key=register.index) == ["R3", "R2", "R1", "R4"]
    assert 'risk-ref">R5<' in closed and 'risk-ref">R5<' not in register
    assert 'data-overdue="true"' in register and "days overdue" in register
    red_chip = html[html.index('data-filter="red"') :]
    assert '</span>Red<span class="chip-count">2</span>' in red_chip[: red_chip.index("</button>")]
    assert '<span class="chip-count is-alert">1</span>' in html
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
    db.add(Risk(tracker_id=tracker.id, ref="R1", description="d", rag="Red"))
    db.commit()
    html = client.get(f"/trackers/{tracker.id}/inputs?week=2026-10-16").get_data(as_text=True)
    assert "Nobody has written this week up yet." in html
    assert "data-copy-last hidden" in html and 'data-headline="Good week"' in html
    assert "1 Red</span>" in html and "Week ending 09 Oct 2026" in html
    assert f'href="/trackers/{tracker.id}/inputs?week=2026-10-09" rel="prev"' in html


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
    assert b'aria-current="page">Risks<' in new_page.data


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
    assert b"Weekly inputs" in client.get(f"/trackers/{tracker.id}/groups").data


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
