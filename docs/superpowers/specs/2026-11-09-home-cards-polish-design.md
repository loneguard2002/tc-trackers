# Trackers home: card polish — design (small change)

Agreed with the owner on 2026-11-09 over the mock-up https://claude.ai/artifact/CZ52c4EyZQs5rzYMN6ngED, which
revised the owner's own screenshot of the home page.

## Changes to each card

1. **Status and forecast apart.** The status pill shows the week's Red, Amber or Green (or "Not set") only. The verdict
   ("Forecast 37 weeks behind target", "No forecast yet") is a second pill: amber with a warning sign when the status
   disagrees with the forecast (Green yet more than a week behind), plain otherwise; the card's edge turns amber then.
2. **Each figure once.** The per-card chart key and "Latest week x / y" go; one key sits above the cards. The Forecast
   box: the forecast date (or "Not yet"), then the weeks before or after target, then "Target dd Mon yyyy", each on
   one line in a smaller font.
3. **Risks wording.** "1 open risk", "N open risks", "No open risks".
4. **In charge.** A line "In charge: Name" ("You" for the viewer); "Nobody yet" in amber when no qualified person is
   in charge (PR #31).
5. **Alerts as one list** with icons, the same layout on every card: warnings for "Weekly update for dd Mon not
   written", "No completions for N days (last dd Mon)", and the status/forecast disagreement; an information line for
   the last completions or "No completions recorded yet".
6. **Actions with icons:** Report (document), Record completions (layers) and, for editors and owners, Write the
   update (pencil) linking to the week's update page.
7. **Filters.** "Commentary missing" becomes "Weekly update not written"; a new chip "Status disagrees with forecast".
8. **Labels.** With neither set: "Business line and regions not set", muted.

The list view uses the same wording. Below-target bars stay distinguished by more than colour (a hatch).

## Non-goals

No new figures, no change to sorting or to the report page.
