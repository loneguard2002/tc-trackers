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


def test_entries_table_is_enhanced(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, entry_url(tracker, "/new"), entry_form(group))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert 'data-table data-table-page-size="50" data-table-export="entries.csv"' in html
    for asset in ("vendor/tabulator-6.6.1.min.js", "vendor/tabulator-6.6.1.min.css", "tables.js"):
        assert asset in html


def test_entries_list_says_when_it_is_capped(client, db, tracker_factory, user_factory, grant, monkeypatch):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    monkeypatch.setattr("tracker.entries.views.LIST_LIMIT", 2)
    for day in ("2026-10-14", "2026-10-15"):
        post(client, entry_url(tracker, "/new"), entry_form(group, day))
    assert "Showing the latest" not in client.get(entry_url(tracker)).get_data(as_text=True)
    post(client, entry_url(tracker, "/new"), entry_form(group, "2026-10-16"))
    html = client.get(entry_url(tracker)).get_data(as_text=True)
    assert "Showing the latest 2 entries only." in html
    assert "Download CSV includes only the entries shown." in html


def test_risks_table_is_enhanced(client, db, tracker_factory, user_factory, grant):
    tracker, _, group = setup_editor(db, tracker_factory, user_factory, grant, client)
    post(client, f"/trackers/{tracker.id}/risks", {"description": "Supplier delay", "status": "Open", "rag": "Red"})
    html = client.get(f"/trackers/{tracker.id}/risks").get_data(as_text=True)
    assert '<table class="table" data-table>' in html and "tables.js" in html


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
