# Spec: Export Expenses Report in PDF and Excel Format

## Overview
Step 10 lets a logged-in user download their own expense history as either a
PDF report or an Excel (.xlsx) spreadsheet. The export honours the same date
range filter that drives the profile page so a user can grab "this month",
"last 3 months", "last 6 months", a custom range, or all-time data. Two new
GET routes (`/expenses/export/pdf` and `/expenses/export/xlsx`) accept the
existing `date_from` / `date_to` query parameters, fetch the owning user's
expenses via a new owner-scoped query helper, render the file in-memory, and
return it as an attachment with a filename that includes the date range. The
profile page gains two small download buttons next to the "+ Add Expense"
button so the export action is one click away from the data the user is
already looking at.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is set and checked)
- Step 4 / 5: Profile page exists and renders user info
- Step 6: Date filter helpers (`_validate_iso_date` and the preset mapping
  are reused so the export honours the same filter contract as `/profile`)
- Step 7: Add Expense (expenses exist to export)

## Routes
- `GET /expenses/export/pdf` — stream a PDF report of the logged-in user's
  expenses scoped by optional `date_from` / `date_to` query params — logged-in only
- `GET /expenses/export/xlsx` — stream an `.xlsx` workbook of the logged-in
  user's expenses scoped by optional `date_from` / `date_to` query params — logged-in only

Both routes:
- Redirect to `/login` when `session["user_id"]` is not set
- Reuse `_validate_iso_date` from `app.py` — invalid / partial date pairs
  fall back to "all time" silently (matching `/profile` behaviour)
- Return the response with `Content-Disposition: attachment; filename=...`
  so the browser triggers a download instead of rendering inline

## Database changes
No database changes. The `expenses` table already has every column the
export needs (`amount`, `category`, `date`, `description`).

## Templates
- **Create:** None.
- **Modify:** `templates/profile.html`
  - In the existing `profile-header` block, next to the `+ Add Expense`
    button, render two small download buttons: one for PDF and one for
    Excel. Each is an `<a>` linking to its export route, passing through
    the current `date_from` and `date_to` so the export matches what the
    user is currently viewing.
  - Use Lucide icons (`file-text` for PDF, `sheet` or `table` for Excel)
    inside the buttons to stay visually consistent with the existing
    iconography on the page.

## Files to change
- `app.py`:
  - Import `send_file` from `flask` and the new query helper
    `get_expenses_for_export` from `database.queries`
  - Add two new view functions `export_expenses_pdf()` and
    `export_expenses_xlsx()`. Each:
    - Redirects to `/login` if not authenticated
    - Validates `date_from` / `date_to` via `_validate_iso_date` (reused);
      if only one is provided, fall back to "all time" — matches `profile()`
    - Calls `get_expenses_for_export(user_id, date_from, date_to)`
    - Builds the file in an in-memory `io.BytesIO` buffer
    - Returns `send_file(buffer, mimetype=..., as_attachment=True, download_name=...)`
    - The download filename includes the user's name (slug-safe) and the
      date range, e.g. `spendly-demo-user-2026-05-01-to-2026-05-23.pdf`
      or `spendly-demo-user-all-time.xlsx`
- `database/queries.py`:
  - Add `get_expenses_for_export(user_id, date_from=None, date_to=None)` —
    returns the full filtered expense list as a list of dicts ordered by
    `date DESC, id DESC`. Unlike `get_recent_transactions` this helper has
    **no `limit`** because the user wants their entire history exported.
    Same `(date_from, date_to)` semantics as the other Step-6 queries:
    both-or-neither, and both must be valid ISO `YYYY-MM-DD` strings.
- `templates/profile.html` — add the two new download buttons to the
  `profile-header` block, passing the current `date_from` / `date_to`
  through `url_for(...)`.
- `static/css/style.css` — add only what is required for the new
  download buttons. Reuse existing button tokens (`var(--accent)`,
  `var(--ink)`, `var(--radius-sm)`, etc.). If a "secondary action"
  variant is needed, introduce it via the existing CSS-variable system
  (e.g. a new `.btn-export` modifier) — never hardcode colours.
- `requirements.txt` — pin the two new dependencies (see below).

## Files to create
None.

## New dependencies
Two new pinned Python packages, added to `requirements.txt`:
- `reportlab==4.2.5` — generates the PDF. Mature, pure-Python, no system
  binaries required.
- `openpyxl==3.1.5` — generates the `.xlsx` workbook. Mature, pure-Python,
  the standard choice for modern Excel files.

Both libraries are MIT/BSD-style licensed and have no native dependencies,
so they install cleanly into the existing `.venv/`.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format `user_id` or dates
  into SQL. Reuse the existing `where = "WHERE user_id = ?"` /
  `params = [user_id]` pattern from `get_recent_transactions`.
- Passwords hashed with werkzeug (no auth changes in this step, but the
  rule still applies to any new code touching credentials)
- Use CSS variables — never hardcode hex values. If a new accent shade is
  needed for the download buttons, add a token in `:root`.
- All templates extend `base.html`
- **Ownership enforcement is mandatory.** Both export routes MUST filter
  by `user_id = session["user_id"]`. A logged-in user must never receive
  another user's data in their export — no "id-in-URL" pattern here, the
  export is always scoped to the session user.
- Both export routes are `GET` only and read-only — no DB writes.
- The PDF must:
  - Include a title (e.g. "Spendly Expense Report"), the user's name,
    the date range label (e.g. "All time" or "2026-05-01 to 2026-05-23"),
    and the total spent
  - Render a table with columns: Date, Description, Category, Amount
  - Display currency as `₹` (Indian Rupees) — use a font that supports the
    rupee glyph (DejaVuSans, bundled with reportlab, supports it; do NOT
    fall back to a missing-glyph box)
  - Footer with a generated-at timestamp
- The Excel workbook must:
  - Have a single worksheet named `Expenses`
  - Row 1 = headers: `Date`, `Description`, `Category`, `Amount (INR)`
  - Subsequent rows = the expense data, newest first
  - The `Amount (INR)` column must be a numeric cell (not a string) so
    Excel can sum/filter it. Use a number format like `#,##0.00`.
  - A summary row at the bottom: `Total` label + `SUM(...)` formula over
    the amount column
- Filenames must be safe: lowercase, hyphenated, ASCII only. Build them
  from the user's name run through a small slugify helper (kept local to
  `app.py` — no new module just for one helper).
- No inline styles in templates.
- The download buttons on `/profile` must preserve the active filter:
  when the user clicks "Export PDF" while viewing "Last 3 Months", the
  PDF must contain the last-3-months data, not all-time data.
- When a user has zero expenses in the selected range, the export must
  still succeed — return an empty (but well-formed) PDF / workbook with
  just the headers and a "No expenses in this date range." line. Never
  return a 404 for an empty export.
- No JS frameworks — the export buttons are plain `<a>` tags, no AJAX.

## Tests to write
File: `tests/test_export_expenses.py`

### Unit tests
| Function | Input | Expected output |
|---|---|---|
| `get_expenses_for_export` | `user_id` with expenses, no date range | all of that user's expenses, newest first |
| `get_expenses_for_export` | `user_id` with no expenses | `[]` |
| `get_expenses_for_export` | `user_id` + valid date range | only expenses inside the range |
| `get_expenses_for_export` | `user_id` + range that excludes everything | `[]` |
| `get_expenses_for_export` | another user's `user_id` | only that user's data — never the calling user's |
| `get_expenses_for_export` | only `date_from` (no `date_to`) | treated as no range — all expenses returned (matches Step-6 contract) |

### Route tests — PDF
`GET /expenses/export/pdf` — unauthenticated:
- Redirects to `/login` (302)

`GET /expenses/export/pdf` — authenticated, has expenses, no date params:
- Returns 200
- `Content-Type` starts with `application/pdf`
- `Content-Disposition` header contains `attachment` and `.pdf`
- Response body starts with the `%PDF-` magic bytes

`GET /expenses/export/pdf?date_from=...&date_to=...` — authenticated, valid range:
- Returns 200
- `Content-Disposition` filename includes the date range

`GET /expenses/export/pdf` — authenticated, zero expenses:
- Returns 200 with a well-formed PDF — never 404 or 500

`GET /expenses/export/pdf?date_from=garbage` — authenticated, invalid date:
- Returns 200 with all-time data — does NOT 500

### Route tests — Excel
`GET /expenses/export/xlsx` — unauthenticated:
- Redirects to `/login` (302)

`GET /expenses/export/xlsx` — authenticated, has expenses:
- Returns 200
- `Content-Type` is `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- `Content-Disposition` header contains `attachment` and `.xlsx`
- Response body opens cleanly with `openpyxl.load_workbook`, and the
  resulting workbook has a sheet named `Expenses` whose row 1 is the
  expected header row

`GET /expenses/export/xlsx` — authenticated, zero expenses:
- Returns 200 with a well-formed workbook — header row present, no data rows

### Ownership / isolation test
A user logged in as user A requests `GET /expenses/export/xlsx`. Before the
test, user B has expenses in the DB. Assertion: the workbook returned to
user A contains only user A's expenses — none of user B's amounts,
descriptions, or categories appear anywhere in the file.

### Template test
`GET /profile` — authenticated, has expenses:
- Response body contains an `<a` with `href` starting with `/expenses/export/pdf`
- Response body contains an `<a` with `href` starting with `/expenses/export/xlsx`
- When the page is loaded with `?date_from=...&date_to=...`, both export
  links carry the same `date_from` and `date_to` query parameters

## Definition of done
- [ ] `GET /expenses/export/pdf` while logged out redirects to `/login`
- [ ] `GET /expenses/export/pdf` while logged in returns a downloadable PDF
      containing the user's expenses, currency rendered as `₹`, with a
      summary block (user name, date range, total)
- [ ] `GET /expenses/export/xlsx` while logged out redirects to `/login`
- [ ] `GET /expenses/export/xlsx` while logged in returns a downloadable
      `.xlsx` with a single `Expenses` sheet, numeric amount column, and a
      `Total` `SUM(...)` formula at the bottom
- [ ] Both exports respect the `date_from` / `date_to` query params and
      fall back to "all time" when the pair is missing or invalid
- [ ] Both exports contain only the logged-in user's data — verified by an
      explicit cross-user isolation test
- [ ] Zero-expense exports succeed (well-formed file, no 404 / 500)
- [ ] The profile page shows two download buttons (PDF + Excel) next to
      `+ Add Expense`, each preserving the current date filter in its URL
- [ ] Download filenames are ASCII-safe, lowercase-hyphenated, and include
      the date range (or `all-time`)
- [ ] No hardcoded colours — any new button styling uses tokens in `:root`
- [ ] `reportlab` and `openpyxl` are pinned in `requirements.txt` and the
      app starts cleanly after a fresh `pip install -r requirements.txt`
- [ ] `pytest` passes for the new `tests/test_export_expenses.py` suite
