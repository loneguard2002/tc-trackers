# Sign-in screen and access approval — design

Agreed with the owner on 2026-11-18 over the mock-up https://claude.ai/artifact/7t6k4wVHHhkLckQgW9xXcQ (sign-in screen,
access requested, approvers' email and Users page, emails to the person, turning a request down).

Today a first Microsoft (Entra) sign-in already creates a `pending` person, shows a holding page and lists them first
on the Users page with Approve. Nobody is told: approvers find out only by opening Users, and the person hears nothing
until they try again. Deleting a pending person clears their Microsoft link, so their next sign-in becomes a new
request. This change tells both sides, and lets a request be turned down for good.

## 1. Sign-in screen

- Two panels, as in the Capacity Planner: on the left, the navy brand panel with the Tradition logo on a white plate,
  "Progress Tracker" and one line, "Weekly progress, forecasts and risks for every tracker, in one place."; on the
  right, "Sign in", a one-line explanation, then the form.
- Order: email address and password, the Sign in button, "or", then **Sign in with Microsoft** (shown only when SSO is
  configured). No footer line.
- The password field has an eye button inside its right edge (44 px square) that shows and hides the password
  (`aria-label` "Show password" / "Hide password", `aria-pressed`). No helper text. The field returns to hidden when the
  form is submitted.
- The Microsoft button follows Microsoft's sign-in button guidance: the four-square logo (red #F25022 top left, green
  #7FBA00 top right, blue #00A4EF bottom left, yellow #FFB900 bottom right), white background, #8C8C8C border, #5E5E5E
  Segoe UI Semibold 15 px text, square corners, 41 px tall; the white version in dark mode too.
- Light and dark follow the existing tokens and design rules (docs/design-rules.md).
- The logo is a local file, `tracker/static/img/tradition-logo.jpg` (the 219 × 41 image the Capacity Planner loads from
  tradition.com; the page's security policy allows only images from the app itself).

## 2. A first Microsoft sign-in: access requested

- The holding page becomes "Access requested": the brand header, an amber "Waiting for approval" marker, "Thanks,
  <first name>. Your access request has been sent.", the address they signed in with, and three steps: signed in with
  Microsoft (time), waiting for an approver ("We have emailed the team who approve access."), "You get an email when you
  are approved". Then "Back to sign in". When email is not configured the second step reads "The team who approve access
  will see it when they next open Progress Tracker."
- A returning pending person sees the same page; nobody is emailed again.

## 3. Who is told, and when

**Approvers** are the active people holding `manage_users` (administrators included). If none has an email address,
the administrators.

| When | Who | What |
|---|---|---|
| First Microsoft sign-in | Approvers (one email, Bcc) | "Progress Tracker: <name> is asking for access": name, email, time, a centred **Review access requests** button to the Users page |
| First Microsoft sign-in | The person | "Progress Tracker: we have your access request" |
| Approved | The person | "Progress Tracker: your access is approved": "The team has approved your access…", the team and role if one was given, a centred **Open Progress Tracker** button |
| Turned down | The person | "Progress Tracker: sorry, your access request was not approved" (wording in the mock-up) |
| Daily, once requests wait longer than the reminder setting | Approvers | One digest of every waiting request, oldest first |

- Approvers also see a count beside **Users** in the menu (people waiting), and the Users page opens with the
  **Waiting for approval** box.
- Every email ends with an Infosec line worded for it ("Did not sign in yourself?", "Did not ask for access to Progress
  Tracker?", for approvers "Do not recognise this person or the request? Do not approve it…"), using the Infosec address
  setting.
- Emails need SMTP to be configured. Without it nothing is sent, nothing fails, and the menu count and Users page still
  show the request.
- Emails never name the approver; the Users page and Activity do.

## 4. Turning a request down

- A new person status, `declined` (shown as "Turned down"), added to the users status check by a migration.
- **Turn down** on a waiting request opens an in-page confirmation, "Turn down <name>?", explaining that they are
  emailed, that signing in again only shows the message and emails nobody, and that the decision can be reversed.
  Buttons: **Turn down**, **Keep waiting**. No typed email: it can be undone.
- A turned-down person keeps their Microsoft link. Signing in again shows "Sorry, your access to Progress Tracker was not
  approved" (mock-up wording) and records the attempt in Activity; no request, no email.
- The Users page shows a **Turned down** box when there are any: name, email, when and by whom, the last attempt to sign
  in again, and **Approve…** (the same team and role choice as a normal approval) and **Delete** (as today).
- Who may turn down: the same people who may approve (`manage_users`).

## 5. Settings (Email settings page)

- **Infosec contact address**, default `infosec@tradition.com`.
- **Remind approvers after (days)**, default 3; 0 turns the reminder off.
- Both are `AppSetting` rows, changed by administrators, each change recorded in Activity.

## 6. The reminder

- Runs in the scheduler cycle. At most one digest a day: the date of the last digest is kept in an `AppSetting` row and
  claimed before sending, so two workers cannot both send it; a failed delivery gives the claim back.

## 7. Email build

- The Tradition logo is attached inline (`cid:tradition-logo`), as the report chart is, with explicit width and height
  and alt text "Tradition", on a white plate in the navy header beside "Progress Tracker". No remote image and no data
  URI: Outlook blocks the first and cannot show the second.
- Table layout with centred buttons that Outlook desktop renders, plus a plain-text part.

## 8. Activity

New entries: access request emailed (to approvers / to the person), request turned down, turned-down sign-in attempt,
approved email sent, reminder digest sent, settings changed.

## Build plan

1. **Sign-in screen**: logo file, layout, eye button, Microsoft button. Tests: the page renders with and without SSO,
   the eye toggles in the browser under the security policy.
2. **Notifications and turning down**: migration, emails, menu count, Users page boxes, turned-down page, settings,
   reminder job. Tests for each email's recipients and wording, the SMTP-off path, the declined sign-in path, the
   reminder's once-a-day claim, and the migration.

## Non-goals

- The Tradition logo header in the weekly report email (backlog).
- The Capacity Planner's Microsoft logo, which has its blue and green squares swapped (a separate repository).
