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

from flask import render_template

from ..formatting import MISSING, fmt_data_uri, fmt_date, fmt_pct
from ..models import EmailTemplate
from ..report.build import Report
from ..report.charts import remaining_chart

CHART_CID = "remaining-chart"

PLACEHOLDERS: dict[str, str] = {
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
}

DEFAULT_SUBJECT = "{{tracker_name}} – week ending {{week_ending}} – {{status}}"
DEFAULT_BODY = """\
<p><strong>{{tracker_name}}</strong>: week ending {{week_ending}}</p>
<p><strong>Status:</strong> {{status}} – {{verdict}}</p>
<p>Forecast completion {{forecast_date}} against a target of {{target_date}}.
{{percent_complete}} complete ({{completed}} of {{total_scope}}; {{remaining}} remaining).</p>
<p>{{headline}}</p>
<p><strong>Needed from you:</strong> {{decisions}}</p>
<p><a href="{{report_link}}">Open the live report</a> (sign-in required).</p>
"""

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
MAX_SUBJECT_LENGTH = 300


def report_link(app_url: str, tracker_id: int, week_ending: date) -> str:
    """The sign-in-protected report URL, built from the configured APP_URL (never from request headers)."""
    return f"{app_url.rstrip('/')}/trackers/{tracker_id}/report?week={week_ending.isoformat()}"


def placeholder_context(report: Report, link: str) -> dict[str, str]:
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
    }


def render_placeholders(text: str, context: dict[str, str]) -> str:
    """Replace ``{{name}}`` with the HTML-escaped value; unknown names are left in place."""

    def substitute(match: re.Match) -> str:
        name = match.group(1)
        return html.escape(str(context[name])) if name in context else match.group(0)

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
    return sanitise_subject(render_placeholders(template_subject, context))


def html_to_text(markup: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h\d>", "\n", markup)
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


def preview_chart_src(report: Report) -> str:
    return fmt_data_uri(remaining_chart(report.rows, report.tracker.unit_label, "png"), "image/png")


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
    chart = remaining_chart(report.rows, report.tracker.unit_label, "png")
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
