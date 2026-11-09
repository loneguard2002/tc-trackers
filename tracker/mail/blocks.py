"""The parts of the report email's message that the block placeholders insert: the figures row, This week, Needed from
you and the risks table.

Each part is ready-made HTML (``Markup``) built from escaped report data. Mail clients get inline styles and tables;
the classes give the Email page preview, which drops inline styles, the same look through ``email-preview.css``.
"""

from __future__ import annotations

import re

from markupsafe import Markup

from ..formatting import MISSING, fmt_date, fmt_num, fmt_rate, fmt_short_date

NOT_SET = "Not set"
NO_UPDATE = "No update was written for this week."

# tone: (background, border, text)
TONES = {
    "plain": ("#ffffff", "#9aa5b8", "#1a1a1a"),
    "green": ("#e3f4ec", "#087553", "#087553"),
    "amber": ("#fdf1dc", "#9a5b00", "#9a5b00"),
    "red": ("#fbe5e9", "#b8283f", "#b8283f"),
    "none": ("#f1f3f7", "#9aa5b8", "#5d6b83"),
}
RAG_TONES = {"Green": "green", "Amber": "amber", "Red": "red"}
MUTED = "#5d6b83"
HEADING = 'style="margin:16px 0 4px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#5d6b83"'


def lines(text: str | None) -> list[str]:
    """The non-empty lines of an owner's text, without a bullet mark typed at the start ("- ", "* ", "• "); a minus
    sign followed by a figure stays."""
    found = []
    for line in (text or "").splitlines():
        line = re.sub(r"^[-*•]\s+", "", line.strip())
        if line:
            found.append(line)
    return found


def _quantity(value: str, unit: str) -> str:
    return f"{value} {unit}".strip() if value != MISSING else NOT_SET


def figure_items(report) -> list[tuple[str, str, str]]:
    """``(label, value, tone)`` for the five boxes, left to right."""
    h = report.headline
    unit = report.tracker.unit_label or ""
    next_week, needed = h.next_week_target, h.required_rate
    next_tone = "plain" if next_week is None or needed is None else "red" if next_week < needed else "green"
    forecast, target = h.forecast_completion, h.target_completion
    forecast_tone = "plain" if forecast is None or target is None else "green" if forecast <= target else "red"
    status = report.inputs.status if report.inputs and report.inputs.status else None
    return [
        ("Next week's target", _quantity(fmt_num(next_week), unit), next_tone),
        ("Needed per week", _quantity(fmt_rate(needed), unit), "plain"),
        ("Target finish", fmt_date(target) if target else NOT_SET, "plain"),
        ("Forecast finish", fmt_date(forecast) if forecast else NOT_SET, forecast_tone),
        ("Status", status or "No status", RAG_TONES.get(status, "none")),
    ]


def figures_html(report) -> Markup:
    cells = []
    for label, value, tone in figure_items(report):
        background, border, colour = TONES[tone]
        label_colour = MUTED if tone == "plain" else colour
        cells.append(
            Markup(
                '<td class="mail-figure mail-tone-{tone}" width="20%" style="border:1px solid {border};'
                'background:{background};border-radius:6px;padding:7px 8px;vertical-align:top">'
                '<div class="mail-figure-label" style="font-size:11px;color:{label_colour}">{label}</div>'
                '<div class="mail-figure-value" style="font-size:14px;font-weight:bold;color:{colour}">{value}</div>'
                "</td>"
            ).format(
                tone=tone,
                border=border,
                background=background,
                label_colour=label_colour,
                label=label,
                colour=colour,
                value=value,
            )  # fmt: skip
        )
    return Markup(
        '<table class="mail-figures" role="presentation" width="100%" cellpadding="0" cellspacing="6" '
        'style="width:100%;table-layout:fixed;border-collapse:separate;border-spacing:6px 0;margin:0 0 4px">'
        "<tr>{cells}</tr></table>"
    ).format(cells=Markup("").join(cells))


def _heading(title: str) -> Markup:
    return Markup('<h3 class="mail-heading" {style}>{title}</h3>').format(style=Markup(HEADING), title=title)


def _bullets(items: list[str]) -> Markup:
    rows = Markup("").join(Markup("<li>{}</li>").format(item) for item in items)
    return Markup('<ul class="mail-bullets" style="margin:0;padding-left:20px">{}</ul>').format(rows)


def this_week_html(report) -> Markup:
    items = lines(report.inputs.headline if report.inputs else None)
    if items:
        return _heading("This week") + _bullets(items)
    empty = Markup('<p class="mail-empty" style="margin:0;color:{muted}">{text}</p>').format(
        muted=MUTED, text=NO_UPDATE
    )
    return _heading("This week") + empty


def needed_html(report) -> Markup:
    items = lines(report.inputs.decisions if report.inputs else None)
    return _heading("Needed from you") + _bullets(items) if items else Markup("")


def risk_rows(report) -> list[tuple[object, bool]]:
    """``(risk, is_new)``: the top open risks, then each risk raised this week that is not among them."""
    new = list(getattr(report, "new_risks", []) or [])
    shown = list(report.top_risks)
    shown += [risk for risk in new if all(risk is not top for top in shown)]
    return [(risk, any(risk is n for n in new)) for risk in shown]


def risks_html(report) -> Markup:
    if not report.open_risks:
        return Markup("")
    cell = "padding:5px 6px;border-bottom:1px solid #f0f2f6;vertical-align:top"
    head = (
        'style="text-align:left;font-weight:bold;color:#5d6b83;font-size:11px;'
        'border-bottom:1px solid #e1e6ee;padding:4px 6px"'
    )
    rows = []
    for risk, is_new in risk_rows(report):
        background, border, colour = TONES[RAG_TONES.get(risk.rag, "none")]
        rag = Markup(
            '<span class="mail-pill mail-tone-{tone}" style="display:inline-block;font-size:11px;font-weight:bold;'
            'padding:2px 6px;border-radius:4px;border:1px solid {border};background:{background};color:{colour}">'
            "{text}</span>"
        ).format(
            tone=RAG_TONES.get(risk.rag, "none"), border=border, background=background, colour=colour,
            text=risk.rag or "–",
        )  # fmt: skip
        new = (
            Markup(
                ' <span class="mail-new" style="font-size:10px;font-weight:bold;color:#b8283f;'
                'border:1px solid #b8283f;border-radius:4px;padding:1px 4px">NEW</span>'
            )
            if is_new
            else Markup("")
        )
        rows.append(
            Markup(
                '<tr><td width="1%" style="{c}">{rag}</td><td style="{c};white-space:nowrap">{ref}</td>'
                '<td style="{c}">{description}{new}</td><td style="{c}">{owner}</td>'
                '<td align="right" style="{c};white-space:nowrap">{due}</td></tr>'
            ).format(
                c=cell,
                rag=rag,
                ref=risk.ref,
                description=risk.description or "–",
                new=new,
                owner=risk.owner_role or "–",
                due=fmt_short_date(risk.target_date),
            )  # fmt: skip
        )
    table = Markup(
        '<table class="mail-risks" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;font-size:13px">'
        "<thead><tr><th {h}>RAG</th><th {h}>Ref</th><th {h}>Risk</th><th {h}>Owner</th>"
        "<th {due}>Due</th></tr></thead><tbody>{rows}</tbody></table>"
    ).format(
        h=Markup(head), due=Markup(head.replace("text-align:left", "text-align:right")), rows=Markup("").join(rows)
    )
    return _heading(f"Risks: {fmt_num(report.open_risks)}") + table


def block_context(report) -> dict[str, Markup]:
    return {
        "figures": figures_html(report),
        "this_week": this_week_html(report),
        "needed_from_you": needed_html(report),
        "risks": risks_html(report),
    }
