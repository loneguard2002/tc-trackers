"""SQLAlchemy models for the progress tracker (spec section 5)."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("auth_source IN ('local', 'sso')", name="auth_source"),
        CheckConstraint("status IN ('pending', 'active', 'disabled')", name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_source: Mapped[str] = mapped_column(Text, default="local", server_default="local")
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return value.strip().lower()


class Tracker(Base):
    __tablename__ = "trackers"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint("week_ending_weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint("last_week_ending >= first_week_ending", name="span_order"),
        CheckConstraint("last_week_ending - first_week_ending <= 357", name="span_52_weeks"),
        CheckConstraint("moving_average_weeks BETWEEN 1 AND 12", name="moving_average_weeks"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    unit_label: Mapped[str] = mapped_column(Text, default="", server_default="")
    group_label: Mapped[str] = mapped_column(Text, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    week_ending_weekday: Mapped[int] = mapped_column(SmallInteger)
    first_week_ending: Mapped[date] = mapped_column(Date)
    last_week_ending: Mapped[date] = mapped_column(Date)
    target_completion: Mapped[date | None] = mapped_column(Date)
    completed_before_first: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    moving_average_weeks: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    send_time: Mapped[time] = mapped_column(Time, default=time(17, 0), server_default=text("'17:00'"))
    send_timezone: Mapped[str] = mapped_column(Text, default="Europe/London", server_default="Europe/London")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()


class TrackerRole(Base):
    __tablename__ = "tracker_roles"
    __table_args__ = (CheckConstraint("role IN ('viewer', 'editor', 'owner')", name="role"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    tracker_id: Mapped[int | None] = mapped_column(ForeignKey("trackers.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text)
    entity: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("tracker_id", "name", name="uq_groups_tracker_id_name"),
        CheckConstraint("baseline >= 0", name="baseline"),
        CheckConstraint("starting_completed >= 0", name="starting_completed"),
        CheckConstraint("ready_not_complete >= 0", name="ready_not_complete"),
        CheckConstraint("rag IN ('Green', 'Amber', 'Red')", name="rag"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    baseline: Mapped[int] = mapped_column(Integer)
    starting_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ready_not_complete: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    planned_completion: Mapped[date | None] = mapped_column(Date)
    rag: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    retired: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CompletionEntry(Base):
    __tablename__ = "completion_entries"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity"),
        Index("ix_completion_entries_tracker_week", "tracker_id", "week_ending"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    week_ending: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()


class Week(Base):
    __tablename__ = "weeks"

    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"), primary_key=True)
    week_ending: Mapped[date] = mapped_column(Date, primary_key=True)
    target: Mapped[int | None] = mapped_column(Integer)
    imported_actual: Mapped[int | None] = mapped_column(Integer)


class ReportInput(Base):
    __tablename__ = "report_inputs"
    __table_args__ = (CheckConstraint("status IN ('Green', 'Amber', 'Red')", name="status"),)

    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"), primary_key=True)
    week_ending: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str] = mapped_column(Text, default="", server_default="")
    decisions: Mapped[str] = mapped_column(Text, default="", server_default="")
    prepared_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Risk(Base):
    __tablename__ = "risks"
    __table_args__ = (
        UniqueConstraint("tracker_id", "ref", name="uq_risks_tracker_id_ref"),
        CheckConstraint("status IN ('Open', 'In progress', 'Closed')", name="status"),
        CheckConstraint("rag IN ('Green', 'Amber', 'Red')", name="rag"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    ref: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    impact: Mapped[str] = mapped_column(Text, default="", server_default="")
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    owner_role: Mapped[str] = mapped_column(Text, default="", server_default="")
    raised_on: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="Open", server_default="Open")
    rag: Mapped[str | None] = mapped_column(Text)
    latest_update: Mapped[str] = mapped_column(Text, default="", server_default="")


class Recipient(Base):
    __tablename__ = "recipients"
    __table_args__ = (UniqueConstraint("tracker_id", "email", name="uq_recipients_tracker_id_email"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, default="", server_default="")


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"), primary_key=True)
    subject: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text)


class ReportSend(Base):
    __tablename__ = "report_sends"
    __table_args__ = (
        CheckConstraint("trigger IN ('scheduled', 'manual')", name="trigger"),
        CheckConstraint("status IN ('sending', 'sent', 'queued', 'failed')", name="status"),
        Index(
            "uq_report_sends_scheduled_week",
            "tracker_id",
            "week_ending",
            unique=True,
            postgresql_where=text("trigger = 'scheduled'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    week_ending: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    recipients: Mapped[list] = mapped_column(JSONB)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
