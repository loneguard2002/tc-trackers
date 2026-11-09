"""Composing the report email: placeholders, subject, HTML and plain-text bodies, inline chart and PDF.

Trust model: the template body is HTML authored by tracker owners, who are trusted users, so it is inserted as
written. Placeholder VALUES come from report data entered by editors and are untrusted, so ``render_placeholders``
HTML-escapes every value.
"""

from __future__ import annotations

import html
import re
from datetime import date
from email.message import EmailMessage
from types import SimpleNamespace

from flask import render_template
from markupsafe import Markup

from ..formatting import MISSING, fmt_data_uri, fmt_date, fmt_num, fmt_pct, fmt_short_date
from ..models import AppSetting, EmailTemplate
from ..report.build import Report
from ..report.charts import email_chart
from .blocks import block_context

CHART_CID = "remaining-chart"

PLACEHOLDERS: dict[str, str] = {
    "summary": "The week in one line: date, status, progress against this week's target, what is left and the risks",
    "tracker_name": "The tracker name",
    "week_ending": "The report week-ending date, for example 16 Oct 2026",
    "status": "The overall Red, Amber or Green status",
    "verdict": "The one-line verdict, for example the forecast against the target",
    "percent_complete": "The percentage of scope completed",
    "completed": "The quantity completed",
    "total_scope": "The total quantity in scope",
    "remaining": "The quantity remaining",
    "forecast_date": "The forecast completion date",
    "target_date": "The target completion date",
    "headline": "The headline entered for the week",
    "decisions": "The decisions or support needed (None when empty)",
    "report_link": "A link to the live report (sign-in required)",
    "figures": "Five boxes: next week's target, needed per week, target finish, forecast finish and status",
    "this_week": "The week's update as bullet points, or a note that none was written",
    "needed_from_you": "The decisions or support needed as bullet points (nothing when there are none)",
    "risks": "The open risks as a table with the new ones marked (nothing when none are open)",
}
# Placeholders whose value is ready-made HTML for the message; they insert nothing in the subject.
BLOCK_PLACEHOLDERS = ("figures", "this_week", "needed_from_you", "risks")

DEFAULT_SUBJECT = "{{summary}}"
DEFAULT_BODY = "{{figures}}\n{{this_week}}\n{{needed_from_you}}\n{{risks}}\n"  # the chart and link come after

REPORT_SUBJECT_KEY = "report_email_subject"  # the app setting holding the one subject every tracker's email uses


def report_subject(session) -> str:
    """The subject template every tracker's email uses, set by an administrator; ``{{summary}}`` until one is saved."""
    stored = session.get(AppSetting, REPORT_SUBJECT_KEY)
    return stored.value if stored is not None and stored.value.strip() else DEFAULT_SUBJECT


def email_template(session, tracker_id: int) -> SimpleNamespace:
    """What a tracker's email is built from: the tool's subject and the tracker's saved body (or the default body).
    A subject saved on the tracker's own template is no longer used."""
    saved = session.get(EmailTemplate, tracker_id)
    return SimpleNamespace(subject=report_subject(session), body_html=saved.body_html if saved else DEFAULT_BODY)


_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
MAX_SUBJECT_LENGTH = 300


def report_link(app_url: str, tracker_id: int, week_ending: date) -> str:
    """The sign-in-protected report URL, built from the configured APP_URL (never from request headers)."""
    return f"{app_url.rstrip('/')}/trackers/{tracker_id}/report?week={week_ending.isoformat()}"


def _plural(count: int, word: str) -> str:
    return f"{fmt_num(count)} {word}" if count == 1 else f"{fmt_num(count)} {word}s"


def _risks_text(open_risks: int, new_rags: list[str | None]) -> str:
    """ "3 risks", with the week's new ones: "3 risks (1 new - red)", "(2 new - 1 red, 1 amber)", "(1 new)"."""
    text = _plural(open_risks, "risk")
    if not new_rags:
        return text
    coloured = [rag for rag in new_rags if rag]
    if not coloured:
        return f"{text} ({len(new_rags)} new)"
    if len(new_rags) == 1:
        return f"{text} (1 new - {coloured[0].lower()})"
    counts = [f"{coloured.count(rag)} {rag.lower()}" for rag in ("Red", "Amber", "Green") if rag in coloured]
    return f"{text} ({len(new_rags)} new - {', '.join(counts)})"


def email_summary(report: Report) -> str:
    """The week in one line, for the subject: ``Network refresh | 06/11/26 : Green | 25 (+5 v +3) of 180 devices
    done (14%) | 155 left | 3 risks (1 new - red)``. A week without a target drops `` v +3``."""
    h = report.headline
    status = report.inputs.status if report.inputs and report.inputs.status else "No status"
    week = f"+{fmt_num(h.this_week_actual or 0)}"
    if h.this_week_target is not None:
        week += f" v +{fmt_num(h.this_week_target)}"
    progress = (
        f"{fmt_num(h.completed)} ({week}) of "
        + " ".join(
            part for part in (fmt_num(h.total_scope), report.tracker.unit_label, "done") if part
        )  # unit optional
        + f" ({fmt_pct(h.pct_complete)})"
    )
    return " | ".join(
        (
            f"{report.tracker.name} | {fmt_short_date(report.week_ending)} : {status}",
            progress,
            f"{fmt_num(h.remaining)} left",
            _risks_text(report.open_risks, report.new_risk_rags),
        )
    )


def placeholder_context(report: Report, link: str) -> dict[str, str | Markup]:
    h = report.headline
    inputs = report.inputs

    def text(value) -> str:
        return str(value).strip() if value not in (None, "") and str(value).strip() else MISSING

    return {
        "tracker_name": text(report.tracker.name),
        "week_ending": fmt_date(report.week_ending),
        "status": text(inputs.status if inputs else None),
        "verdict": text(h.verdict),
        "percent_complete": fmt_pct(h.pct_complete),
        "completed": str(h.completed),
        "total_scope": str(h.total_scope),
        "remaining": str(h.remaining),
        "forecast_date": fmt_date(h.forecast_completion),
        "target_date": fmt_date(h.target_completion),
        "headline": text(inputs.headline if inputs else None),
        "decisions": text(inputs.decisions if inputs else None) if inputs and inputs.decisions else "None",
        "report_link": link,
        "summary": email_summary(report),
        **block_context(report),
    }


def render_placeholders(text: str, context: dict[str, str]) -> str:
    """Replace ``{{name}}`` with the HTML-escaped value (ready-made ``Markup`` as it is); unknown names stay."""

    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in context:
            return match.group(0)
        value = context[name]
        return str(value) if isinstance(value, Markup) else html.escape(str(value))

    return _PLACEHOLDER_RE.sub(substitute, text)


def unknown_placeholders(*texts: str) -> list[str]:
    """Placeholder names used in ``texts`` that are not in ``PLACEHOLDERS`` (shown as warnings in the preview)."""
    found: list[str] = []
    for text in texts:
        for name in _PLACEHOLDER_RE.findall(text):
            if name not in PLACEHOLDERS and name not in found:
                found.append(name)
    return found


def sanitise_subject(subject: str) -> str:
    """Plain-text subject: entities decoded, then every control character (CR and LF included) collapsed to a space."""
    return _CONTROL_RE.sub(" ", html.unescape(subject)).strip()[:MAX_SUBJECT_LENGTH]


def render_subject(template_subject: str, context: dict[str, str]) -> str:
    plain = {name: "" if isinstance(value, Markup) else value for name, value in context.items()}
    return sanitise_subject(render_placeholders(template_subject, plain))


def html_to_text(markup: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h\d>", "\n", markup)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)</div>", " ", text)
    text = re.sub(r"(?i)</t[dh]>", "  ", text)
    text = re.sub(r"(?s)<style.*?</style>|<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def render_email_html(report: Report, template: EmailTemplate | None, link: str, chart_src: str) -> tuple[str, str]:
    """The ``(subject, html)`` pair; ``chart_src`` is ``cid:remaining-chart`` in the email, a data URI in previews."""
    context = placeholder_context(report, link)
    subject_source = template.subject if template else DEFAULT_SUBJECT
    body_source = template.body_html if template else DEFAULT_BODY
    body = render_placeholders(body_source, context)
    page = render_template(
        "mail/email_body.html",
        body_html=body,
        chart_src=chart_src,
        unit_label=report.tracker.unit_label,
        link=link,
    )
    return render_subject(subject_source, context), page


def chart_png(report: Report) -> bytes:
    """The email's chart: remaining against plan, with each week's target and what was done."""
    return email_chart(report.rows, report.tracker.unit_label, report.week_ending, "png")


def preview_chart_src(report: Report) -> str:
    return fmt_data_uri(chart_png(report), "image/png")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tracker"


def attachment_name(report: Report) -> str:
    """The PDF's file name, as attached to the email."""
    return f"{_slug(report.tracker.name)}-week-ending-{report.week_ending.isoformat()}.pdf"


def build_report_email(
    report: Report,
    template: EmailTemplate | None,
    recipients: list[str],
    link: str,
    pdf: bytes,
    sender: str = "",
) -> EmailMessage:
    """The report email: HTML with the inline PNG chart, a plain-text alternative and the PDF attached.

    ``To`` is the sender's own address and recipients go in ``Bcc``. When ``sender`` is empty ``smtp.send_message``
    fills ``From`` and ``To`` from the configured sender.
    """
    subject, page = render_email_html(report, template, link, f"cid:{CHART_CID}")
    msg = EmailMessage()
    msg["Subject"] = subject
    if sender:
        msg["From"] = sender
        msg["To"] = sender
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(f"{html_to_text(page)}\n\nView the full report: {link}\n")
    msg.add_alternative(page, subtype="html")
    chart = chart_png(report)
    msg.get_payload()[1].add_related(chart, "image", "png", cid=f"<{CHART_CID}>", disposition="inline")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=attachment_name(report))
    return msg


# A deliberately conservative address: no quotes, commas, semicolons, angle brackets or other header specials.
_EMAIL_RE = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")


def normalise_recipient(raw: str) -> tuple[str, str | None]:
    """``(email, error)``: stripped, lower-cased, and checked against a conservative address pattern."""
    email = (raw or "").strip().lower()
    if len(email) > 254:
        return email, "The email address is too long."
    if not _EMAIL_RE.fullmatch(email):
        return email, "Enter a valid email address."
    return email, None
