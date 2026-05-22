# Spec: Edit Expense

## Overview
Step 8 lets a logged-in user update one of their existing expenses through a
dedicated form page at `/expenses/<int:id>/edit`. The route currently exists as a
placeholder; this step upgrades it to a full GET + POST handler that pre-fills
the form with the existing row, validates submitted changes, updates the
`expenses` table, and redirects back to the profile page on success. Two new
query helpers — `get_expense_by_id` and `update_expense` — are added to
`database/queries.py`. The transactions table on the profile page gains a row-
level "Edit" action so users can navigate to the form.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is set and checked)
- Step 4 / 5: Profile page exists and lists transactions
- Step 7: Add Expense (`add_expense.html`, `CATEGORIES`, `insert_expense` —
  this step reuses the same category list and form styling)

## Routes
- `GET /expenses/<int:id>/edit` — render the edit-expense form pre-filled with the current values — logged-in only, owner-only
- `POST /expenses/<int:id>/edit` — validate and update the expense — logged-in only, owner-only

## Database changes
No database changes. The `expenses` table already has all required columns.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`
  - Form with `method="POST"` and `action="{{ url_for('edit_expense', id=expense.id) }}"`
  - Same fields as `add_expense.html`:
    - `amount` — number input, step="0.01", min="0.01", required, pre-filled with current amount
    - `category` — `<select>` with the 7 fixed categories from `CATEGORIES`, current category pre-selected
    - `date` — `<input type="date">`, required, pre-filled with current date
    - `description` — text input, optional, max 200 chars, pre-filled with current description
  - Submit button labelled "Save Changes" and a cancel link back to `/profile`
  - Display error message when validation fails, re-populating the submitted values (not the original ones)
- **Modify:** `templates/profile.html`
  - Add an "Edit" action to each transaction row, linking to `/expenses/<id>/edit`
  - Add a new "Actions" column header (or render the icon link inside the existing amount/last column — implementer's call, but the icon must be clearly clickable and aligned with the row)

## Files to change
- `app.py` — replace the placeholder `/expenses/<int:id>/edit` route with a GET+POST handler:
  - Auth gate: redirect to `/login` if not authenticated
  - Owner gate: if the expense does not exist or does not belong to `session["user_id"]`, redirect to `/profile` with a flashed error (do NOT 404 in a way that leaks ownership)
  - GET: load the expense via `get_expense_by_id`, render `edit_expense.html`
  - POST: validate (same rules as Add Expense), call `update_expense`, redirect to `/profile` with a success flash
- `database/queries.py`:
  - Add `get_expense_by_id(expense_id, user_id)` — returns a dict (or `None`) scoped to the given user so other users' rows can never be loaded
  - Add `update_expense(expense_id, user_id, amount, category, expense_date, description)` — parameterised `UPDATE ... WHERE id = ? AND user_id = ?`; returns the number of rows affected
  - Extend `get_recent_transactions` to include `id` in each returned dict so the profile template can build edit links
- `templates/profile.html` — render an "Edit" link/icon per transaction row pointing at `/expenses/<id>/edit`

## Files to create
- `templates/edit_expense.html` — the edit-expense form template

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Foreign keys PRAGMA must be enabled on every connection (already done in `get_db()`)
- Unauthenticated access to both GET and POST `/expenses/<id>/edit` must redirect to `/login`
- **Ownership enforcement is mandatory.** Every read and write of an expense in this route MUST be scoped by `user_id = session["user_id"]`. A logged-in user must never be able to view or modify another user's expense by guessing IDs.
- Validation rules for POST (identical to Add Expense):
  - `amount`: required, must be a positive number greater than 0 (parse with `float()`; catch `ValueError`; reject non-finite via `math.isfinite`)
  - `category`: required, must be one of the 7 fixed categories in `CATEGORIES`
  - `date`: required, must be a valid `YYYY-MM-DD` date (validate via `_validate_iso_date` helper already in `app.py`)
  - `description`: optional; strip whitespace; cap at 200 chars; store `NULL` if blank
- On validation error, re-render the form with the error message and the submitted (not the original) values pre-filled
- After successful update, redirect to `url_for("profile")` — do NOT render the form again
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles
- Currency must always display as ₹ — never £ or $
- Reuse the existing form CSS classes (`auth-section`, `auth-card`, `form-group`, `form-input`, `btn-submit`, etc.) from `add_expense.html` so the two forms look consistent

## Tests to write
File: `tests/test_edit_expense.py`

### Unit tests
| Function | Input | Expected output |
|---|---|---|
| `get_expense_by_id` | valid `expense_id` belonging to the user | dict with all expense fields |
| `get_expense_by_id` | `expense_id` belonging to a **different** user | `None` |
| `get_expense_by_id` | non-existent `expense_id` | `None` |
| `update_expense` | valid args, expense owned by user | rows-affected = 1; DB row reflects new values |
| `update_expense` | `expense_id` owned by **another** user | rows-affected = 0; original row unchanged |
| `update_expense` | `description=None` | row updated with `description` stored as `NULL` |

### Route tests
`GET /expenses/<id>/edit` — unauthenticated:
- Redirects to `/login` (302)

`GET /expenses/<id>/edit` — authenticated, owner:
- Returns 200
- Response body contains current amount, category, date, description pre-filled
- Response body contains the category `<select>` with all 7 options, current one selected
- Response body contains `<form` with `method` POST

`GET /expenses/<id>/edit` — authenticated, NOT owner (expense belongs to another user):
- Redirects to `/profile` (302)
- No data leaks in the response

`GET /expenses/<id>/edit` — authenticated, expense does not exist:
- Redirects to `/profile` (302)

`POST /expenses/<id>/edit` — unauthenticated:
- Redirects to `/login` (302)

`POST /expenses/<id>/edit` — authenticated, owner, valid data:
- Redirects to `/profile` (302)
- DB row reflects the updated amount, category, date, and description

`POST /expenses/<id>/edit` — authenticated, NOT owner:
- Redirects to `/profile` (302)
- Target row in DB is **unchanged**

`POST /expenses/<id>/edit` — authenticated, owner, missing amount:
- Returns 200 (re-renders form)
- Response body contains an error message

`POST /expenses/<id>/edit` — authenticated, owner, amount = 0:
- Returns 200 (re-renders form)
- Response body contains an error message

`POST /expenses/<id>/edit` — authenticated, owner, non-numeric amount:
- Returns 200 (re-renders form)
- Response body contains an error message

`POST /expenses/<id>/edit` — authenticated, owner, invalid category:
- Returns 200 (re-renders form)
- Response body contains an error message

`POST /expenses/<id>/edit` — authenticated, owner, invalid date string:
- Returns 200 (re-renders form)
- Response body contains an error message

`POST /expenses/<id>/edit` — authenticated, owner, cleared description:
- Redirects to `/profile` (302)
- Row updated with `description = NULL`

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login`
- [ ] Visiting `/expenses/<id>/edit` for an expense owned by another user redirects to `/profile` (no data leak)
- [ ] Visiting `/expenses/<id>/edit` for a non-existent expense redirects to `/profile`
- [ ] Visiting `/expenses/<id>/edit` for an owned expense shows a form pre-filled with the current amount, category, date, and description
- [ ] The category dropdown contains exactly: Food, Transport, Bills, Health, Entertainment, Shopping, Other — with the current category selected
- [ ] Submitting a valid edit redirects to `/profile` and the updated values appear in the transactions table
- [ ] Submitting with a missing or zero amount re-renders the form with an error and the submitted values retained
- [ ] Submitting with an invalid category re-renders the form with an error
- [ ] Submitting with an invalid date re-renders the form with an error
- [ ] Clearing the description and saving stores `NULL` for description
- [ ] An attacker-style POST to `/expenses/<id>/edit` for another user's expense leaves that row unchanged
- [ ] The profile page transactions table shows an "Edit" link/icon per row that navigates to `/expenses/<id>/edit`
