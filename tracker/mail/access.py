"""Access requests: who is emailed when someone signs in with Microsoft for the first time, is approved or is turned
down, and the daily reminder to approvers (design 2026-11-18,
docs/superpowers/specs/2026-11-18-signin-and-approval-design.md).

Approvers are the active people holding ``manage_users`` (administrators included). An email goes out only when the
mail server is configured; a failed delivery is logged and never stops the sign-in, approval or turn-down that sent it.
Each email carries the Tradition logo as an inline attachment (``cid:``), which Outlook shows without asking, unlike a
remote image, and unlike a data URI, which it cannot show at all. The caller commits.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import current_app, render_template
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ..audit import record
from ..auth.permissions import user_permissions
from ..models import AppSetting, User
from . import smtp
from .compose import html_to_text, normalise_recipient

logger = logging.getLogger(__name__)

INFOSEC_KEY = "access_infosec_email"
DEFAULT_INFOSEC = "infosec@tradition.com"
REMINDER_DAYS_KEY = "access_reminder_days"
DEFAULT_REMINDER_DAYS = 3
MAX_REMINDER_DAYS = 90
REMINDER_DAYS_ERROR = f"Remind approvers after a whole number of days from 0 (no reminder) to {MAX_REMINDER_DAYS}."
LAST_REMINDER_KEY = "access_reminder_last_sent"
LOGO_CID = "tradition-logo"
TIME_FORMAT = "%d %b %Y at %H:%M UTC"


def _setting(session, key: str) -> str | None:
    return session.scalar(select(AppSetting.value).where(AppSetting.key == key))


def infosec_email(session) -> str:
    return _setting(session, INFOSEC_KEY) or DEFAULT_INFOSEC


def reminder_days(session) -> int:
    value = _setting(session, REMINDER_DAYS_KEY)
    return int(value) if value is not None and value.isdigit() else DEFAULT_REMINDER_DAYS


def parse_reminder_days(value: str | None) -> tuple[int | None, str | None]:
    """``(days, error)`` for the text of the reminder box."""
    text = (value or "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 3 or int(text) > MAX_REMINDER_DAYS:
        return None, REMINDER_DAYS_ERROR
    return int(text), None


def parse_infosec_email(value: str | None) -> tuple[str | None, str | None]:
    email, error = normalise_recipient(value or "")
    return (None, "The Infosec contact must be one email address.") if error else (email, None)


def mail_configured(session) -> bool:
    cfg = smtp.get_smtp_config(session)
    return bool(cfg["host"] and cfg["from_"])


def approvers(session) -> list[User]:
    """The active people who may approve access, by email."""
    people = session.scalars(select(User).where(User.status == "active").order_by(User.email))
    return [person for person in people if "manage_users" in user_permissions(session, person)]


def _logo() -> bytes:
    with open(os.path.join(current_app.static_folder, "img", "tradition-logo.jpg"), "rb") as handle:
        return handle.read()


def build_email(session, subject: str, template: str, *, to: str | None = None, bcc: list[str] | None = None,
                **context) -> EmailMessage:  # fmt: skip
    """One access email: HTML with the inline logo, and a plain-text alternative."""
    app_url = current_app.config["APP_URL"].rstrip("/")
    page = render_template(
        f"mail/access/{template}.html", app_url=app_url, infosec=infosec_email(session), logo_cid=LOGO_CID, **context
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    if to:
        msg["To"] = to
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg.set_content(html_to_text(page) + "\n")
    msg.add_alternative(page, subtype="html")
    msg.get_payload()[1].add_related(_logo(), "image", "jpeg", cid=f"<{LOGO_CID}>", disposition="inline")
    return msg


def _send(session, msg: EmailMessage, kind: str, person: User, recipients: list[str], actor_id: int | None) -> bool:
    try:
        smtp.send_message(msg)
    except Exception:
        logger.exception("The %s email about user %s could not be sent", kind, person.id)
        return False
    record(
        session, user_id=actor_id, tracker_id=None, action="access_email_sent", entity="user", entity_id=person.id,
        target_user_id=person.id, detail={"email": kind, "recipients": recipients},
    )  # fmt: skip
    return True


def first_name(person: User) -> str:
    return (person.full_name or "").split(" ")[0] or person.email


def request_received(session, person: User) -> bool:
    """Email the approvers and the person after a first Microsoft sign-in. ``True`` when the approvers were emailed."""
    if not mail_configured(session):
        return False
    asked = person.created_at.astimezone(timezone.utc).strftime(TIME_FORMAT)
    team = [approver.email for approver in approvers(session) if approver.id != person.id]
    emailed = bool(team) and _send(
        session,
        build_email(
            session,
            f"Progress Tracker: {person.full_name} is asking for access",
            "request_approvers",
            bcc=team,
            person=person,
            asked=asked,
            days=reminder_days(session),
        ),  # fmt: skip
        "request_approvers",
        person,
        team,
        None,
    )
    _send(
        session,
        build_email(
            session,
            "Progress Tracker: we have your access request",
            "request_person",
            to=person.email,
            person=person,
            name=first_name(person),
            asked=asked,
        ),  # fmt: skip
        "request_person",
        person,
        [person.email],
        None,
    )
    return emailed


def approved(session, person: User, actor: User, team: str | None, role: str | None) -> bool:
    if not mail_configured(session):
        return False
    return _send(
        session,
        build_email(
            session,
            "Progress Tracker: your access is approved",
            "approved",
            to=person.email,
            name=first_name(person),
            team=team,
            role=role,
        ),  # fmt: skip
        "approved",
        person,
        [person.email],
        actor.id,
    )


def declined(session, person: User, actor: User) -> bool:
    if not mail_configured(session):
        return False
    asked = person.created_at.astimezone(timezone.utc).strftime("%d %b %Y")
    return _send(
        session,
        build_email(
            session,
            "Progress Tracker: sorry, your access request was not approved",
            "declined",
            to=person.email,
            name=first_name(person),
            asked=asked,
        ),  # fmt: skip
        "declined",
        person,
        [person.email],
        actor.id,
    )


def waiting_longer_than(session, days: int, now_utc: datetime) -> list[User]:
    cutoff = now_utc - timedelta(days=days)
    return list(
        session.scalars(
            select(User).where(User.status == "pending", User.created_at <= cutoff).order_by(User.created_at, User.id)
        )
    )


def send_due_reminder(session, now_utc: datetime) -> bool:
    """Once a UTC day, email the approvers every request older than the reminder setting. The day is claimed before
    sending, so two workers cannot both send it; a failed delivery gives the claim back for the next run."""
    days = reminder_days(session)
    if days == 0 or not mail_configured(session):
        return False
    now_utc = now_utc.astimezone(timezone.utc)
    waiting = waiting_longer_than(session, days, now_utc)
    team = [approver.email for approver in approvers(session)]
    if not waiting or not team:
        return False
    today = now_utc.date().isoformat()
    previous = _setting(session, LAST_REMINDER_KEY)
    claim = (
        insert(AppSetting)
        .values(key=LAST_REMINDER_KEY, value=today)
        .on_conflict_do_update(index_elements=["key"], set_={"value": today}, where=AppSetting.value != today)
        .returning(AppSetting.key)
    )
    if session.execute(claim).scalar_one_or_none() is None:
        session.rollback()
        return False
    session.commit()
    rows = [(person, person.created_at.astimezone(timezone.utc).strftime("%d %b %Y")) for person in waiting]
    msg = build_email(
        session, f"Progress Tracker: {len(waiting)} access request{'' if len(waiting) == 1 else 's'} waiting",
        "reminder", bcc=team, rows=rows, days=days,
    )  # fmt: skip
    try:
        smtp.send_message(msg)
    except Exception:
        if previous is None:
            session.execute(AppSetting.__table__.delete().where(AppSetting.key == LAST_REMINDER_KEY))
        else:
            session.execute(update(AppSetting).where(AppSetting.key == LAST_REMINDER_KEY).values(value=previous))
        session.commit()
        raise
    record(
        session, user_id=None, tracker_id=None, action="access_reminder_sent", entity="app_settings",
        entity_id="access_requests", detail={"waiting": len(waiting), "recipients": team},
    )  # fmt: skip
    session.commit()
    return True
