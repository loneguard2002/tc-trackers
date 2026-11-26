"""Limits on PDF and PNG report downloads: one Chromium at a time in each process, and at most ten downloads per person
in any minute (security audit 2026-11-25, Medium 2)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import post, sign_in
from sqlalchemy import func, select

from tracker.mail import sending
from tracker.models import ExportRequest, Recipient, ReportSend
from tracker.report import limits, render, views
from tracker.report.render import BUSY_MESSAGE, RenderBusy

# --- The render slot (no database) ------------------------------------------------------------------------------


def test_a_render_waits_for_the_slot_then_gives_up():
    with render._render_slot(0):
        with pytest.raises(RenderBusy, match="already being prepared"):
            render.html_to_pdf("<p>x</p>", wait=0.05)


def test_the_slot_is_given_back_when_a_render_fails():
    with pytest.raises(RuntimeError), render._render_slot(0):
        raise RuntimeError("Chromium crashed")
    with render._render_slot(0):  # free again: it would raise RenderBusy otherwise
        pass


def test_a_busy_render_reads_as_a_reason_on_the_email_screens():
    assert isinstance(RenderBusy(), ValueError) and str(RenderBusy()) == BUSY_MESSAGE


# --- Downloads (database) ---------------------------------------------------------------------------------------


@pytest.fixture
def small_tracker(tracker_factory):
    return tracker_factory(name="Core Rollout", first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 9, 25))


@pytest.fixture
def viewer(client, logged_in_user, grant, small_tracker):
    grant(logged_in_user, small_tracker, "viewer")
    return logged_in_user


@pytest.fixture
def renders(monkeypatch):
    """Count conversions instead of starting Chromium for each."""
    done = []

    def fake(html, width=1100, wait=0):
        done.append(wait)
        return b"%PDF-fake"

    monkeypatch.setattr(views, "html_to_pdf", fake)
    monkeypatch.setattr(views, "html_to_png", fake)
    return done


def _download(client, tracker, extension="pdf", **args):
    query = "&".join(f"{name}={value}" for name, value in args.items())
    return client.get(f"/trackers/{tracker.id}/report.{extension}" + (f"?{query}" if query else ""))


def _counted(db, user) -> int:
    return db.scalar(select(func.count()).select_from(ExportRequest).where(ExportRequest.user_id == user.id))


def test_ten_downloads_a_minute_then_the_next_is_refused(client, db, small_tracker, viewer, renders):
    for n in range(10):
        assert _download(client, small_tracker, "png" if n % 2 else "pdf").status_code == 200
    response = _download(client, small_tracker, week="2026-09-11", view="new")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/trackers/{small_tracker.id}/report?week=2026-09-11&view=new")
    assert limits.LIMIT_MESSAGE in client.get(response.headers["Location"]).get_data(as_text=True)
    assert len(renders) == 10 and _counted(db, viewer) == 10  # the refused one is not drawn or counted


def test_downloads_older_than_a_minute_do_not_count(client, db, small_tracker, viewer, renders):
    db.add_all([ExportRequest(user_id=viewer.id, at=func.now() - timedelta(seconds=61)) for _ in range(10)])
    db.commit()
    assert _download(client, small_tracker).status_code == 200


def test_the_limit_is_per_person(app, client, db, small_tracker, viewer, user_factory, grant, renders):
    db.add_all([ExportRequest(user_id=viewer.id) for _ in range(10)])
    db.commit()
    assert _download(client, small_tracker).status_code == 302
    other = user_factory()
    grant(other, small_tracker, "viewer")
    colleague = app.test_client()
    sign_in(colleague, other)
    assert _download(colleague, small_tracker).status_code == 200


def test_a_download_deletes_counts_older_than_an_hour(client, db, small_tracker, viewer, renders):
    db.add(ExportRequest(user_id=viewer.id, at=func.now() - limits.KEEP_REQUESTS - timedelta(minutes=1)))
    db.commit()
    _download(client, small_tracker)
    assert _counted(db, viewer) == 1


def test_a_download_waits_only_briefly_for_its_turn(client, small_tracker, viewer, renders):
    _download(client, small_tracker)
    assert renders == [views.EXPORT_WAIT_SECONDS] and views.EXPORT_WAIT_SECONDS <= 5


def test_a_download_while_another_is_drawn_goes_back_with_a_message(client, small_tracker, viewer, monkeypatch):
    monkeypatch.setattr(views, "EXPORT_WAIT_SECONDS", 0.05)
    with render._render_slot(0):  # another download is being drawn in this process
        response = _download(client, small_tracker, week="2026-09-11")
    assert response.status_code == 302
    assert BUSY_MESSAGE in client.get(response.headers["Location"]).get_data(as_text=True)


def test_send_now_while_a_report_is_drawn_says_so(client, db, tracker_factory, user_factory, grant, monkeypatch):
    tracker = tracker_factory()
    db.add(Recipient(tracker_id=tracker.id, email="a@example.com"))
    db.commit()
    owner = user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)

    def busy(html, wait=0):
        raise RenderBusy()

    monkeypatch.setattr(sending, "html_to_pdf", busy)
    response = post(client, f"/trackers/{tracker.id}/mail/send?week=2026-09-11", follow_redirects=True)
    assert BUSY_MESSAGE in response.get_data(as_text=True)
    assert db.query(ReportSend).count() == 0
