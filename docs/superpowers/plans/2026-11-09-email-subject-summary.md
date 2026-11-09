# Email Subject Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The weekly report email's subject becomes a one-line summary of the week, from one `{{summary}}` placeholder, in one subject for the whole tool that an administrator sets.

**Architecture:** `tracker/mail/compose.py` gains the summary phrase and a `{{summary}}` placeholder; the subject source moves from each tracker's `email_templates.subject` to the `app_settings` key `report_email_subject` (default `{{summary}}`), edited on the admin Email settings page. Sending and the tracker Email page read the tool's subject; the tracker page shows it read-only.

**Tech Stack:** Flask 3.1, SQLAlchemy 2, Jinja, Postgres, pytest, Playwright; no migration.

**Spec:** docs/superpowers/specs/2026-11-09-email-subject-summary-design.md

## Global Constraints

- Example line, verbatim: `Network refresh | 06/11/26 : Green | 25 (+5 v +3) of 180 devices done (14%) | 155 left | 3 risks (1 new - red)`
- Date dd/mm/yy; status "No status" when none; "(+5)" with no weekly target; "(+0 v +3)" when nothing done.
- Risks: "1 risk" singular; "0 risks"; new = open and raised within the report week (week_ending − 6 days .. week_ending); one new coloured: "(1 new - red)"; several: "(2 new - 1 red, 1 amber)", Red, Amber, Green order, lower case; a new risk without RAG counts but is not coloured ("(1 new)"); no new: no brackets.
- Subject is plain text, at most 300 characters (`MAX_SUBJECT_LENGTH`, `MAX_SUBJECT`).
- Who edits the subject: the `manage_email_settings` permission (the admin Email settings page). Change audited.
- Saved per-tracker subjects stop being used; nothing is deleted; no migration.
- Targeted tests only (owner's standing rule): run the files named in each task.

## Review Focus

- A report week after the last recorded week (future or in progress): `this_week_actual` is None, so the bracket reads "(+0 v +3)", never "(+None …)" — test in Task 1.
- Thousands: totals above 999 use the app's separators ("1,170 of 2,400") — test in Task 1.
- A blank or whitespace-only subject posted on the admin page is refused with 400 and nothing is stored — test in Task 2.
- A tracker with a saved custom subject still sends the tool's subject — test in Task 2.
- The tracker Email page's placeholder chips must not insert into the read-only subject — browser test in Task 3.

---

### Task 1: The summary phrase and `{{summary}}`

**Files:**
- Modify: `tracker/formatting.py` (add `fmt_short_date`)
- Modify: `tracker/report/build.py` (`Report.new_risk_rags`, filled in `build_report`)
- Modify: `tracker/mail/compose.py` (`email_summary`, `PLACEHOLDERS["summary"]`, `placeholder_context`, `DEFAULT_SUBJECT`)
- Test: `tests/test_mail.py`, `tests/test_report.py` (new-risk selection)

**Interfaces:**
- Produces: `fmt_short_date(value: date | None) -> str` ("06/11/26", `MISSING` for None).
- Produces: `Report.new_risk_rags: list[str | None]` — the RAG of each open risk raised in the report week; dataclass field with `default_factory=list` so existing constructors keep working.
- Produces: `email_summary(report: Report) -> str`; `placeholder_context(...)["summary"]`; `DEFAULT_SUBJECT = "{{summary}}"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_mail.py`, using `synthetic_report()` and `dataclasses.replace` on `report.headline`:

```python
def summary_for(**changes):
    report, _ = synthetic_report()
    report.inputs = SimpleNamespace(status="Green", headline="", decisions="")
    report.headline = dataclasses.replace(report.headline, **({
        "completed": 25, "total_scope": 180, "remaining": 155, "pct_complete": 25 / 180,
        "this_week_actual": 5, "this_week_target": 3} | changes))
    report.tracker.name = "Network refresh"
    report.week_ending = date(2026, 11, 6)
    report.open_risks, report.new_risk_rags = 3, ["Red"]
    return report

def test_summary_matches_the_agreed_line():
    assert email_summary(summary_for()) == (
        "Network refresh | 06/11/26 : Green | 25 (+5 v +3) of 180 devices done (14%) | 155 left | 3 risks (1 new - red)")

@pytest.mark.parametrize("changes, part", [
    ({"this_week_target": None}, "25 (+5) of 180"),
    ({"this_week_actual": 0}, "25 (+0 v +3) of 180"),
    ({"this_week_actual": None}, "25 (+0 v +3) of 180"),
    ({"completed": 1170, "total_scope": 2400, "remaining": 1230}, "1,170 (+5 v +3) of 2,400 devices done"),
])
def test_summary_progress_cases(changes, part): ...  # part in email_summary(summary_for(**changes))

@pytest.mark.parametrize("open_risks, rags, text", [
    (3, [], "| 3 risks"), (1, [], "| 1 risk"), (0, [], "| 0 risks"),
    (3, ["Amber", "Red"], "3 risks (2 new - 1 red, 1 amber)"),
    (2, [None], "2 risks (1 new)"), (2, ["Red", None], "2 risks (2 new - 1 red)"),
])
def test_summary_risk_cases(open_risks, rags, text): ...  # endswith(text); no "()" anywhere

def test_summary_without_a_status_says_so(): ...  # report.inputs = None -> " : No status | "

def test_summary_is_a_known_placeholder_and_the_default_subject():
    assert DEFAULT_SUBJECT == "{{summary}}" and "summary" in PLACEHOLDERS
```

In `tests/test_report.py`, one database test: risks raised on week_ending − 7 (not new), week_ending − 6 and week_ending (new), a Closed one raised in the week (not new), and one with `raised_on=None` (not new) → `build_report(...).new_risk_rags` lists exactly the two new ones' RAGs.

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_mail.py tests/test_report.py -q` — Expected: the new tests fail (ImportError / AttributeError).

- [ ] **Step 3: Implement.** `fmt_short_date` as `f"{d:%d/%m/%y}"`. In `build_report`, new = open risks with `raised_on` in `[week_ending - timedelta(days=6), week_ending]`, ordered Red, Amber, Green, None. `email_summary` uses `fmt_num`, `fmt_pct`, the tracker's `unit_label`; a missing `this_week_actual` counts as 0. Update `test_mail.py`'s existing assertion that the default subject starts with "Stub tracker – week ending" to the new line's start ("Stub tracker | ").

- [ ] **Step 4: Run** the same command — Expected: all pass.

- [ ] **Step 5: Commit** — `feat: {{summary}} placeholder: the week in one line`

### Task 2: One subject for the whole tool, set on the admin Email settings page

**Files:**
- Modify: `tracker/mail/compose.py` (`REPORT_SUBJECT_KEY`, `report_subject`, `email_template`)
- Modify: `tracker/mail/sending.py` (both `session.get(EmailTemplate, …)` call sites use `email_template`)
- Modify: `tracker/admin/smtp.py`, `tracker/templates/admin/smtp.html` (a "Report email" section with a Subject field and the placeholder list)
- Modify: `tracker/activity/labels.py` if it labels changed keys (label "Report email subject")
- Test: `tests/test_mail.py`, `tests/test_auth.py` or the file holding the SMTP page tests (grep `admin/smtp`)

**Interfaces:**
- Consumes: `DEFAULT_SUBJECT`, `PLACEHOLDERS` (Task 1).
- Produces: `REPORT_SUBJECT_KEY = "report_email_subject"`; `report_subject(session) -> str` (the stored value, else `DEFAULT_SUBJECT`); `email_template(session, tracker_id: int) -> SimpleNamespace(subject, body_html)` — the tool's subject with the tracker's saved body or `DEFAULT_BODY`.

- [ ] **Step 1: Write the failing tests:**
  - `test_saved_tracker_subject_is_not_used`: a tracker with `EmailTemplate(subject="Old {{status}}", body_html="<p>b</p>")` and `app_settings` `report_email_subject` = `"[PMO] {{summary}}"` → the queued/test email's `Subject` starts with `"[PMO] "` and contains `" | "`; the body is `<p>b</p>`.
  - `test_without_a_saved_subject_the_summary_is_used`: no app setting → `report_subject(db) == "{{summary}}"`.
  - Admin page: GET shows `name="report_email_subject"` with value `{{summary}}`; POST with the SMTP fields plus `report_email_subject="[PMO] {{summary}}"` stores it and the `smtp_settings_updated` entry's `changed` includes `"report_email_subject"`; POST with `"   "` or 301 characters → 400 and nothing stored; a non-administrator holder of `manage_email_settings` may change it (200/302, stored).

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_mail.py <smtp page test file> -q` — Expected: new tests fail.

- [ ] **Step 3: Implement.** Subject posted is whitespace-collapsed (`" ".join(value.split())`), required, at most 300 characters, refused with `abort(400, description="The report email subject is required and must be at most 300 characters.")`. Saved with the SMTP settings in the same POST and audit entry. Page copy: section "Report email", help "The subject of every tracker's weekly email. {{summary}} gives the week in one line; the other placeholders also work."; update the page lede so it no longer says each tracker sets its own template subject.

- [ ] **Step 4: Run** the same command plus `tests/test_activity_labels.py` — Expected: all pass.

- [ ] **Step 5: Commit** — `feat: one report email subject for the whole tool, set by an administrator`

### Task 3: The tracker Email page shows the tool's subject read-only

**Files:**
- Modify: `tracker/mail/views.py` (`_page`, `_preview`, `save_template`)
- Modify: `tracker/templates/mail/settings.html`, `tracker/static/email.js`
- Test: `tests/test_mail.py` (or the file with the Email page tests — grep `/mail"`), `tests/test_email_settings_browser.py`

**Interfaces:**
- Consumes: `report_subject(session)`, `email_template(session, tracker_id)` (Task 2).

- [ ] **Step 1: Write the failing tests:**
  - The Email page shows `<input id="subject" … readonly>` with no `name` attribute, the tool's subject as its value, and the note "Set by an administrator for every tracker."; the preview's subject line is the rendered summary.
  - `save_template` with a posted `subject` ignores it: an existing row keeps its old `subject`, a new row is created with `subject="{{summary}}"`; the body saves as before. Posting without `subject` succeeds.
  - Browser: focusing the subject then clicking a placeholder chip inserts into the body, not the subject; no CSP or script errors.

- [ ] **Step 2: Run** `WT=$PWD ../tools/acc-test.sh tests/test_mail.py tests/test_email_settings_browser.py -q` — Expected: new tests fail.

- [ ] **Step 3: Implement.** `values["subject"]` is `report_subject(db)`; the subject input keeps `id="subject"` (email.js reads it) but drops `name` and gains `readonly`; email.js tracks focus for the body only and leaves `saved.subject`/dirty logic working. `save_template` validates the body only.

- [ ] **Step 4: Run** the same command — Expected: all pass.

- [ ] **Step 5: Commit** — `feat: the tracker Email page shows the tool's subject read-only`
