# Spec: Delete Expense

## Overview
Step 9 lets a logged-in user permanently remove one of their own expenses from
the profile page. The current placeholder `GET /expenses/<int:id>/delete`
route is upgraded to a **POST-only** handler so deletion cannot be triggered
by link prefetching, browser caching, or a stray click on a hyperlink. A new
`delete_expense` query helper is added to `database/queries.py` that runs a
parameterised `DELETE ... WHERE id = ? AND user_id = ?`, returning the number
of rows affected so the route can detect ownership mismatches. The profile
page transactions table gains a per-row delete button rendered as a small
form (POSTing to the route) sitting alongside the existing Edit icon, gated
by a native `confirm()` dialog so a user cannot delete a row by accident.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is set and checked)
- Step 4 / 5: Profile page exists and lists transactions
- Step 7: Add Expense (`CATEGORIES`, validation patterns reused for context)
- Step 8: Edit Expense (`get_expense_by_id` already returns owner-scoped
  rows; the profile transactions table already exposes `tx.id` and a per-row
  actions column)

## Routes
- `POST /expenses/<int:id>/delete` — delete the expense if it belongs to the logged-in user, then redirect to `/profile` — logged-in only, owner-only

Note: the existing placeholder is `GET /expenses/<int:id>/delete`. This step
**replaces** it with a POST-only route. Any direct `GET` request to that URL
must return a 405 (Flask's default when the method is not allowed) — a
destructive action must never be reachable via GET.

## Database changes
No database changes. The `expenses` table already has all required columns
and the `ON DELETE` semantics are not needed here (we delete the row
directly, not via cascade).

## Templates
- **Create:** None.
- **Modify:** `templates/profile.html`
  - In the existing `col-actions` cell, render a small inline `<form method="POST" action="{{ url_for('delete_expense', expense_id=tx.id) }}">` containing a single icon button (trash icon) styled to match the existing edit icon.
  - The form must include an `onsubmit="return confirm('Delete this expense? This cannot be undone.');"` handler so the user has to confirm before the row is removed.
  - The button must have a descriptive `aria-label` (e.g. `Delete ₹{amount} expense on {date}`) for screen readers.

## Files to change
- `app.py` — replace the placeholder `/expenses/<int:expense_id>/delete` route with a POST-only handler:
  - Restrict to `methods=["POST"]`
  - Auth gate: redirect to `/login` if not authenticated
  - Owner gate: call the new `delete_expense` helper scoped by `session["user_id"]`. If the helper returns `0` rows affected, flash an error (do NOT leak whether the row existed for another user); otherwise flash a success message
  - Always redirect to `url_for("profile")` afterwards — no template render
- `database/queries.py`:
  - Add `delete_expense(expense_id, user_id)` — parameterised `DELETE FROM expenses WHERE id = ? AND user_id = ?`; returns the number of rows affected so callers can detect ownership mismatches without a second read
- `templates/profile.html` — render a per-row delete button (POST form + confirm) inside the existing `col-actions` cell, alongside the Edit icon
- `static/css/style.css` — add only what is strictly required to align the new delete button next to the existing Edit icon. Reuse the existing `row-action` class. If a destructive-state variant is needed (e.g. a red hover colour), introduce it via the existing CSS-variable system (e.g. a new `--accent-danger` token in `:root` and a `.row-action--danger` modifier).

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Foreign keys PRAGMA must be enabled on every connection (already done in `get_db()`)
- Route MUST be `POST`-only. A `GET` request to `/expenses/<id>/delete` must return Flask's default 405 Method Not Allowed
- Unauthenticated `POST` must redirect to `/login`
- **Ownership enforcement is mandatory.** The delete query MUST be scoped by both `id` and `user_id = session["user_id"]`. A logged-in user must never be able to delete another user's expense by guessing IDs. The route must not branch on a separate read of the row — the safety is in the single owner-scoped `DELETE`.
- The route must always redirect to `/profile` after a delete attempt — never re-render a template
- After a successful delete (rows affected = 1), flash a success message ("Expense deleted." or similar)
- After an unsuccessful delete (rows affected = 0), flash a generic error ("Expense not found." or similar) — do not reveal whether the row existed at all
- The confirm dialog MUST be triggered before the form is submitted — use the `onsubmit="return confirm(...)"` pattern so disabling JS only prevents accidental deletes, never enables them
- Use CSS variables — never hardcode hex values. If a "danger" colour is needed, add a new token to `:root` (e.g. `--accent-danger`)
- All templates extend `base.html`
- No inline styles
- Currency must always display as ₹ — never £ or $
- Reuse the existing `row-action` class for the delete icon so it lines up with the existing Edit icon

## Tests to write
File: `tests/test_delete_expense.py`

### Unit tests
| Function | Input | Expected output |
|---|---|---|
| `delete_expense` | valid `expense_id` belonging to the user | rows-affected = 1; row no longer present in DB |
| `delete_expense` | `expense_id` belonging to a **different** user | rows-affected = 0; original row still present in DB |
| `delete_expense` | non-existent `expense_id` | rows-affected = 0; no side effects |
| `delete_expense` | calling twice on the same id | first call returns 1; second call returns 0 |

### Route tests
`GET /expenses/<id>/delete` — any user state:
- Returns 405 Method Not Allowed (destructive actions must not be reachable via GET)

`POST /expenses/<id>/delete` — unauthenticated:
- Redirects to `/login` (302)
- Target row in DB is **unchanged**

`POST /expenses/<id>/delete` — authenticated, owner, expense exists:
- Redirects to `/profile` (302)
- Row no longer present in DB
- Follow-through GET to `/profile` shows a success flash message

`POST /expenses/<id>/delete` — authenticated, NOT owner (expense belongs to another user):
- Redirects to `/profile` (302)
- Target row in DB is **unchanged**
- Response does not leak the existence of the other user's expense

`POST /expenses/<id>/delete` — authenticated, expense does not exist:
- Redirects to `/profile` (302)
- No DB side effects
- Follow-through GET to `/profile` shows a generic "not found" flash

`POST /expenses/<id>/delete` — authenticated, owner, repeated submission (idempotency check):
- First POST deletes the row and redirects
- Second POST to the same URL redirects to `/profile` with a "not found" flash — no error, no 500

### Template test
`GET /profile` — authenticated, has expenses:
- Response body contains a `<form` with `action="/expenses/<id>/delete"` and `method="POST"` for each transaction row
- The form contains an `onsubmit` attribute calling `confirm(`
- The delete button has an `aria-label` mentioning the amount and date

## Definition of done
- [ ] `GET /expenses/<id>/delete` returns 405 (no GET access to a destructive route)
- [ ] `POST /expenses/<id>/delete` while logged out redirects to `/login` and leaves the row unchanged
- [ ] `POST /expenses/<id>/delete` for an owned expense removes the row and redirects to `/profile` with a success flash
- [ ] `POST /expenses/<id>/delete` for another user's expense leaves that row unchanged and redirects to `/profile` with a generic "not found" flash (no data leak)
- [ ] `POST /expenses/<id>/delete` for a non-existent id redirects to `/profile` with a generic "not found" flash and causes no side effects
- [ ] Repeating a delete on the same id is idempotent — no 500, just the "not found" flash
- [ ] The profile transactions table shows a delete icon (trash) per row alongside the existing Edit icon
- [ ] Clicking the delete icon triggers a native confirm dialog; cancelling does NOT delete; confirming DOES delete
- [ ] The delete button has a screen-reader-accessible `aria-label`
- [ ] After deletion, the transactions table on `/profile` no longer shows the deleted row and the summary stats reflect the new totals
- [ ] No hardcoded colours — any danger styling uses a CSS variable in `:root`
