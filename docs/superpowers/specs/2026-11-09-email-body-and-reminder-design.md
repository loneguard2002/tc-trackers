# Weekly report email body, person in charge and update reminder — design

Agreed with the owner on 2026-11-09 over the mock-up https://claude.ai/artifact/BPsiV9qzRw19NB7Lfyaxg5 (the
"Chosen direction" email). One pull request, at the owner's request ("add this to the other change and implement").

## Intent

The subject now carries the week in one line (PR #30). The message under it repeated most of that line. The message
becomes a short status sheet that says only what the subject cannot: the figures that show whether the plan holds, the
owner's update, what readers are asked for, the risks and the chart. A missing update must be visible, and the person in
charge of the tracker is reminded the day before so that it is rarely missing.

## 1. The tracker Email page shows the subject as text

The read-only Subject box is replaced by the subject as it will be sent for the previewed week, in plain text, with
the note "Set by an administrator for every tracker." Holders of `manage_email_settings` also see a "Change in Email
settings" link to the admin page. The Email template section text becomes "The message sent with the report. The PDF
is attached and the chart is shown under the message." The live preview and the unsaved-changes note keep working.

## 2. The message

In this order, each part left out when it has nothing to show unless stated:

1. **Figures**: five boxes in one row, left to right:
   - *Next week's target*: the next week's target quantity with the unit. Red when it is below the rate needed per
     week, green when it meets or beats it, plain when either figure is missing.
   - *Needed per week*: the rate needed to finish by the target date, one decimal, with the unit. Plain.
   - *Target finish*: the target completion date ("18 Jun 2027"). Plain.
   - *Forecast finish*: the forecast completion date. Green when on or before the target finish, red when after it,
     plain when either date is missing.
   - *Status*: the week's Red, Amber or Green, filled in that colour; grey "No status" when none was entered.
   - A figure with no value reads "Not set". Plain boxes have a grey outline.
2. **This week**: the owner's weekly update (the report input's headline), one bullet per non-empty line. Always
   shown; with no update it reads "No update was written for this week."
3. **Needed from you**: the decisions entered for the week, one bullet per non-empty line. No box around it.
4. **Risks: N**: N is the number of open risks. A table with aligned columns RAG, Ref, Risk, Owner, Due (dd/mm/yy):
   the report's top open risks, plus every open risk raised in the report week (marked NEW) that is not already among
   them. No open risks: the part is left out.
5. **The chart**: one chart with both axes titled. Left axis: quantity remaining, with the plan, actual and forecast
   lines. Right axis: quantity per week, with bars for each week's target and for what was done, up to the report
   week, and next week's target. Bottom axis: week ending.
6. One link to the live report and the note that the PDF is attached (as today).

The message stays an owner-editable HTML template. Parts 1–4 come from four new placeholders, `{{figures}}`,
`{{this_week}}`, `{{needed_from_you}}` and `{{risks}}`, whose values are ready-made HTML (built from escaped data); the
new default message is those four in order. The chart and the link stay in the email around the message. Saved
messages identical to the old default are removed so those trackers get the new default; any other saved message is
kept, and its owner can use "Reset to default".

The HTML must survive mail clients: tables and inline styles, plus classes so that the Email page preview (which drops
inline styles) looks the same through `email-preview.css`.

## 3. Person in charge

Each tracker gets one *person in charge*: someone with Editor or Owner on the tracker by any route, who can therefore
write the weekly update.

- Set on the tracker's Settings page (owners), in the Scheduled sending section, from the people who qualify.
- Required: a new tracker (New tracker screen and workbook import) gets its creator. Settings refuses an empty choice
  when the field is posted; a form without the field keeps the current value.
- Existing trackers: the migration sets the one person given Owner directly on the tracker when there is exactly one;
  the others start with nobody.
- With nobody set, or a person who no longer qualifies (role removed, disabled), the Settings and Email pages show a
  warning asking for one. Changes are recorded in the Activity log.

## 4. Reminder 24 hours before the automatic send

- For an active tracker with automatic sending on, when its next send is due within 24 hours and the update (headline)
  for that week has not been written, the scheduler emails the person in charge once for that week.
- Nobody qualified in charge: the people given Owner directly on the tracker get it instead.
- The email names the tracker, when the report goes out, and links to the page where the update is written.
- At most one reminder per tracker and week (a new `report_reminders` table); a failed delivery is retried on the next
  scheduler run. Sent reminders are recorded in the Activity log.

## Approaches considered

- **Block placeholders in the owner's template (chosen):** keeps the existing editor, preview and reset; the default
  gives everyone the new layout. Owners who want their own wording keep it.
- **A fixed layout with no template:** simplest to render, but removes a feature owners use and the per-tracker
  message.
- **One `{{report}}` placeholder for the whole layout:** cannot reorder or drop parts.

## Calls made by the builder

- "Required" was read as the owner's answer to "required, or optional with a fallback"; the fallback to direct owners
  stays only for trackers still waiting for a person in charge.
- Forecast after target is red straight away (the open amber question was not answered).
- The risk heading gives the count only; NEW marks the new risks in the table.
- The four block placeholders insert nothing in the subject.

## Non-goals

- The report page and the PDF charts and layout do not change.
- No reminder for manual sending; no reminder about the status or decisions alone.
