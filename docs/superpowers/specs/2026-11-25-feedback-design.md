# Feedback: ideas and problems from the people who use the tracker

Agreed with the owner on 25 Nov 2026 from the "Feedback feature" canvas
(https://claude.ai/artifact/GsqbHSLGYp93GzEeiLksFf, artboards 1 to 7).

## Why

The people who use Progress Tracker have ideas and run into problems, and today there is no route for either other than
an email to whoever they know. The owner wants every idea and problem to reach them, to be kept, and to become a
conversation: the owner reviews it, replies with an update or a question, and the sender can answer. The goal is a
product the user base helps to improve.

## Goals

1. **A Feedback link on every page.** Every signed-in page shows "Feedback on this page" at the top right of the page
   content, on the line of the page title. It opens a pop-up (artboard 1):
   - "What is it?": **An idea** or **Something is wrong** (a two-button switch; An idea is selected first).
   - "In one line" (required, at most 150 characters).
   - Details: labelled "Tell us more" for an idea (help: "Optional. A sentence or two is plenty."), "What happened?" for
     a problem (placeholder: "What you did, what you expected, and what happened instead."; help: "Steps to see it
     again help us fix it sooner."). At most 5,000 characters. Optional for an idea, required for a problem.
   - "Screenshots and files": Add files, drop files on the box, or paste a screenshot with Ctrl+V; each file listed with
     its name, size and a remove button; help "Up to 5 files, 5 MB each: pictures, PDF, Word, Excel or text."
   - "Send this page with it" (ticked): the page's title and address, and the browser (from the user agent and the
     window size), shown as one line under the box ("Core Rollout › Report, week ending 11 Sep 2026 · Edge on
     Windows").
   - "Sent as [name] ([email]) from your account, so the reply comes back to you."
   - Cancel, Send feedback. Without JavaScript the link goes to a page with the same form.
2. **After sending** (artboard 2): "Thank you, [first name]", "Your idea is with the people who run Progress Tracker…"
   (or "Your report is with…" for a problem), the reference ("Reference FB-0042"), the summary and kind with the page,
   and Send another / Close.
3. **Every message is a request kept in the app.** It gets a reference FB- and its id padded to four digits, a kind
   (Idea, Problem), a status, the sender, the page, the files, and a conversation. Statuses: **New**, **Under review**,
   **Waiting for an answer**, **Planned**, **Done**, **Will not do**, **Withdrawn**. Open = New, Under review, Waiting
   for an answer, Planned; closed = Done, Will not do, Withdrawn.
4. **The feedback address is a setting, never in the code.** Admin › Email settings gains a **Feedback** section
   (artboard 4):
   - "Send feedback to": one address or several separated by commas (each a valid address, at most 10, stored in
     `app_settings`); empty by default. Note: "Saved as a setting, not in the code; change it here at any time. Until
     an address is set, messages are kept in Admin › Feedback only."
   - "Feedback link": "Show the Feedback link" (on by default). Off hides the link and the form page for everyone;
     requests already sent stay readable and answerable.
   - "Send a test": a sample feedback email to the address(es) above.
   - Saved with the page's Save, by people with "Manage email settings", as the rest of that page.
5. **The email to the feedback address** (artboard 3), sent when a request is created and when the sender answers or
   adds a message, if an address is set and SMTP is configured:
   - From the application's address, To the feedback address(es), **Reply-To the sender**.
   - Subject: "Idea from [sender]: [summary]" / "Problem from [sender]: [summary]"; for a later message "[sender]
     answered: [summary] (FB-0042)".
   - Body: the kind and reference, the summary, the details, a table (From with their name, Page as a link, Sent, Browser,
     Files), an "Open in Progress Tracker" button to the request, and "Reply to this email to answer [sender]
     directly. Every message is also kept under Admin › Feedback."
   - The files are attached when together they come to 10 MB or less; otherwise the Files row lists them and says they
     are in the request.
   - A failed or skipped send never loses the request: the request records that the email was not sent and why
     ("Email not sent: no feedback address set" / "…: the mail server refused it").
6. **Admin › Feedback** (artboard 5), for people with the new permission **Manage feedback** (below): the standard
   table (the toolkit in `lists/_table.html` and `lists.js`):
   - Search (reference, summary, details, sender, page).
   - A Kind filter: "Ideas and problems", "Ideas", "Problems".
   - Status buttons with counts: **Open** (the default view), **New**, **Waiting for an answer**, **Planned**,
     **Closed**, **All**.
   - Columns, each sortable: Ref, Last activity (the default order, newest first), Kind, Summary, From, Page, Status,
     and Replies (a count).
   - The standard footer ("Showing 1–5 of 7 · 7 open"), paging past 25, the view in the address, cards on a phone.
   - A "Feedback" item in the sidebar's Administration list with the count of New requests (as Users shows its
     waiting count).
7. **Reviewing a request** (artboard 6): opening a request from the table shows it in a panel on the right, in the
   way the permission sets panel works; without JavaScript it is its own page.
   - Head: the kind and reference, when it was received, the summary, "From [sender] · [page link]", and **Status**
     (a select of all seven statuses; saving a status change records it in the conversation as "Status: Planned").
   - The conversation, oldest first: the sender's messages, the reviewers' replies (each marked Update or Question),
     status changes, and the files under the message they came with (pictures as thumbnails, other files as named
     links). A request whose email failed shows that in the conversation.
   - Reply: **Update** or **Question** (a switch), "Your update" / "Your question", Attach (same rules as the form),
     "Email [sender]" (ticked), and "Send the update" / "Ask the question". A question sets the status to Waiting for
     an answer. An update leaves the status as chosen in the head.
   - The reply email to the sender: Subject "Update on your idea: [summary] (FB-0042)" / "A question about your
     report: [summary] (FB-0042)"; the reply, an "Answer in Progress Tracker" (question) or "See it in Progress
     Tracker" (update) button to the sender's request, Reply-To the reviewer.
8. **My feedback** (artboard 7): a sidebar link "My feedback", shown once the person has sent a request, with the
   count of requests that have a reply they have not opened. The page lists their requests in the standard table
   (Summary, Kind, Sent, Status, Last activity; a "New reply" mark), and a request opens in the right-hand panel:
   - The conversation as the reviewer sees it, the reviewers shown as "Progress Tracker team".
   - While the request is open: a box, "Your answer" when it is Waiting for an answer (help: "Goes to the team, and the
     request moves back to Under review.") or "Add a message" otherwise, with Attach and Send. An answer moves Waiting
     for an answer to Under review.
   - **Withdraw request** (open requests only), with a confirm ("Withdraw this request? The team will see that you
     withdrew it."): the status becomes Withdrawn and the box goes.
   - A closed request is read-only.
9. **Who.** Everyone signed in sees the link and can send feedback. A request, its conversation and its files are seen
   only by its sender and by people with Manage feedback. **Manage feedback** is a new permission in the Application
   group of permission sets ("Manage feedback": "Read, reply to and change the status of feedback in Admin ›
   Feedback."); administrators hold every permission, as today.
10. **Recorded in Activity:** a request sent, a reply (Update or Question), a status change, an answer or message from
    the sender, a withdrawal, and the feedback settings changed.

## Non-goals

- No reading of email replies into the app: an email reply to the feedback email goes to the sender's mailbox and an
  email reply to a reviewer's email goes to the reviewer's, outside the app.
- No voting, public list of ideas, or tags; no assigning a request to one reviewer.
- No deleting requests or files from the app in this work.
- No reopening a closed request: the sender sends a new one.

## Constraints

- Strict Content Security Policy: no inline script or style, no `style=` attributes; ES5 scripts in `tracker/static`.
- British English, no contractions; the copy above is the copy.
- The app rejects request bodies over 1 MB (`MAX_CONTENT_LENGTH`). The feedback form, a reply and a sender's message
  raise the limit for their own routes to fit 5 files of 5 MB plus the text; every other route keeps 1 MB.
- Files: at most 5 per message, 5 MB each. Allowed: PNG, JPEG, GIF, WebP, PDF, DOCX, XLSX, TXT, CSV, checked by content
  as well as by name; anything else is refused with the reason. A file is only ever served to its request's sender
  and to people with Manage feedback, with `X-Content-Type-Options: nosniff`; pictures inline, everything else as a
  download (`Content-Disposition: attachment`). SVG and HTML are never accepted.
- Emails go through the existing mail settings (`tracker/mail/smtp.py`); nothing is sent while SMTP is not configured.
- Retention: no retention period is set for feedback or its files in this work. Feedback and screenshots can hold
  personal data, so the owner checks with the Data Protection Officer whether one is needed.

## Approaches

- **Chosen: everything in the database.** Requests, messages and files in PostgreSQL (files in their own table, as
  report sends keep their PDFs), emails sent when SMTP is configured, a failed send recorded on the request. One
  backup and one access check for everything; costs database space, kept in check by the file limits.
- Rejected: files on the server's disk. A smaller database, but a backed-up folder that survives redeploys and path
  handling the app has nowhere else.
- Rejected: email only. Cannot hold statuses, replies or My feedback, and loses everything until SMTP is set up.

## Calls made (the owner may change these)

- 5 MB a file (the canvas said 10 MB): screenshots are well under 5 MB, and 5 files of 10 MB would make a 50 MB
  request through a server that takes 1 MB today.
- Files are attached to the feedback email only up to 10 MB together, so mail servers do not refuse the message.
- "My feedback" is a sidebar link (the name at the top right is a label, not a menu), shown once the person has sent
  something.
- The sender can add a message to an open request at any time, not only when asked a question.
- Withdrawing sends no email; it shows in the conversation and the table.
- The details are required for a problem and optional for an idea.
- **Activity carries no feedback content.** An entry names the reference, the kind, the action (sent, Update, Question,
  status from and to, answer, withdrawn) and who did it, never the summary, details, reply text or file names, because
  people who read Activity need not hold Manage feedback. The reference links to the request only for people with
  Manage feedback.
- **Unread replies:** a request records when its sender last opened it. A reviewer's Update, Question or status change
  after that time makes it "New reply" (whether or not it was emailed); opening the request (its panel or its page)
  clears it, open or closed. The sidebar count is the number of the sender's requests with such a reply.
- **Reviewers may act on any request, closed ones included.** They can reply and change the status of a Done, Will not
  do or Withdrawn request; a Question on a closed request reopens it as Waiting for an answer. Only the sender is barred
  from reopening.
- **The Replies column** counts the reviewers' Updates and Questions; the sender's messages, status changes and email
  notes are not counted.
- **Active accounts only** see the link and use the feedback pages, as with every other page. When a sender's account
  is no longer active, reviewers can still reply in the app, and "Email [sender]" is unticked and disabled with
  "[sender] can no longer be emailed: their account is not active."
- **Send a test** goes to the saved address(es), with the hint "Save first: the test goes to the saved address."

## Left to the builder

Table and column names, the reference padding beyond four digits, the routes, how the panel loads (following the
permission sets panel), how a pasted screenshot is added to the file field, thumbnail sizing, and the message layout,
as long as the behaviour, copy and access rules above hold and every page passes the Content Security Policy.
