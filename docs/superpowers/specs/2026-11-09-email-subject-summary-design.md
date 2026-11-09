# Email subject as the week's summary — design (small change)

Chosen approach: C, one `{{summary}}` placeholder that produces the whole subject line, so the line keeps one fixed
shape on every tracker. (B, a few phrase placeholders an owner could reorder, was the first choice and was replaced
by C at the owner's request; A, one placeholder per value, could not handle the special cases.) The email body is a
separate, later change.

## Intent

The owner wants the weekly report email's subject to be a short, scannable summary of the week, so the inbox line
alone says how the tracker stands. The current default ("Network refresh – week ending 06 Nov 2026 – Green") gives
neither progress nor risks, and its date is long.

## The subject

    Network refresh | 06/11/26 : Green | 25 (+5 v +3) of 180 devices done (14%) | 155 left | 3 risks (1 new - red)

New default subject: `{{summary}}`.

| Part | Example | Rules |
|---|---|---|
| Tracker name | Network refresh | As now. |
| Date | 06/11/26 | The report week-ending date as dd/mm/yy. |
| Status | Green | The week's Red, Amber or Green; "No status" when none was entered. |
| Progress | 25 (+5 v +3) of 180 devices done (14%) | Completed so far, then in brackets this week's completions against this week's target, then the total scope with the tracker's unit, then the percentage complete. No weekly target that week: "(+5)". Nothing done: "(+0 v +3)". |
| Left | 155 left | The quantity remaining. |
| Risks | 3 risks (1 new - red) | Open risks, then the open risks raised during the report week with their RAG in lower case. "1 risk" in the singular. Several new: "(2 new - 1 red, 1 amber)", Red before Amber before Green. A new risk without a RAG is counted but not coloured: "(1 new)". No new risks: no brackets. No open risks: "0 risks". |

The existing placeholders all stay, so saved templates and bodies keep working. `{{summary}}` appears in the settings
page's list of placeholders with a one-line description.

## Saved subjects

A data migration switches every saved subject that is exactly the old default to `{{summary}}`. A subject an owner
has reworded is left alone. (Today one of three trackers has a saved subject, and it is the old default.)

## Calls I made

- **"No entry" case dropped:** an earlier message proposed "(no entry v +3)" for a week with nothing recorded. The
  data cannot tell that apart from a week where nothing was done (a completion entry is always above zero), so both
  show "(+0 v +3)".
- **What counts as new:** a risk is new when it is open and was raised within the report week (the six days before
  the week-ending date, and that date). A risk raised and closed in the same week is not counted.
- **Plain text and length:** the subject stays plain text, capped at the existing 300 characters.

## Non-goals

- The email body (the next conversation).
- A change in the week-on-week percentage; only this week's quantity against its target.
- Letting owners reorder or reword parts of the summary.

## Left to the builder

Where the summary function lives (beside `placeholder_context` in `tracker/mail/compose.py` is the obvious place), and
the migration number (0009).
