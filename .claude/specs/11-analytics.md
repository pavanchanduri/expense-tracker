# Spec: Analytics

## Overview
Step 11 replaces the "Coming Soon" stub on `/analytics` with a real
insights page that goes beyond what `/profile` already shows. The
profile page covers *this filter window*: totals, recent transactions,
and a single category breakdown. Analytics is the *time-series* view:
how spending has trended over the last several months, how it compares
to the previous period, which weekdays the user spends most on, and
which individual expenses dominate the bill. Like `/profile`, the page
honours the same `date_from` / `date_to` filter contract from Step 6
(presets + custom range), but additionally always renders a fixed
12-month monthly-trend chart so the long view is one click away
regardless of the active filter. Charts are rendered as plain SVG /
CSS bars — no charting library, no JS framework.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is set and checked)
- Step 6: Date filter helpers (`_validate_iso_date`, `_resolve_presets`,
  `_resolve_date_range_args` are reused so the analytics filter contract
  matches `/profile`)
- Step 7: Add Expense (expenses exist to analyse)

## Routes
- `GET /analytics` — already wired (currently renders the Coming Soon
  stub). This step keeps the URL and `@login_required` decorator,
  swaps the view body to gather analytics data and render the new
  template — logged-in only

No new routes.

## Database changes
No database changes. Every metric in this step is derived from existing
columns on `expenses` (`amount`, `category`, `date`).

## Templates
- **Create:** None.
- **Modify:** `templates/analytics.html`
  - Delete the Coming Soon card markup entirely; replace with the real
    analytics layout.
  - Extends `base.html` (already does).
  - Top bar mirrors `/profile`: a "Spending insights" heading and the
    same date-filter row (preset pills + custom range form). Reuse the
    existing `.profile-filter`, `.filter-pills`, `.filter-pill`, and
    `.filter-custom` styles so visually it matches the rest of the app.
  - Below the filter, four sections:
    1. **Headline KPIs** — four small cards: Total spent (in-range),
       Average per day (in-range), Highest spending month
       (all-time, label + amount), This-month-vs-last-month delta
       (₹ change and % change, colour-coded — red for higher spending,
       green for lower).
    2. **Monthly trend** — vertical bar chart of the last 12 calendar
       months of total spend (always all-time, not affected by the
       filter — this is the long view). Each bar is a `<div>` with an
       inline `height` style proportional to that month's spend.
       Month labels under each bar. Tallest month highlighted with the
       accent colour.
    3. **Spending by weekday** — seven horizontal bars (Mon–Sun) of
       total spend within the active filter range. Used to surface
       "which day of the week do I spend the most?". Bars rendered the
       same way as the existing `.category-breakdown` bars on the
       profile.
    4. **Top expenses** — table of the five largest single expenses
       within the active filter range (Date, Description, Category,
       Amount). Each row links to the corresponding edit page via
       `url_for('edit_expense', expense_id=...)`.
  - Each section gets an empty-state: "No data for this range." or
    similar, when the underlying list is empty. Never break the layout.
  - Lucide icons may be used for section headings (`trending-up`,
    `calendar-days`, `award`) for visual consistency with `/profile`.

## Files to change
- `app.py`:
  - Remove the current placeholder `analytics()` body.
  - Replace with a view that:
    - Calls `_resolve_date_range_args(request)` and flashes the error
      string when the range is invalid (same as `profile()`).
    - Computes `presets` / `active_preset` / `filter_label` exactly
      like `profile()` (extract a small helper if duplication grows —
      otherwise inline is fine for now).
    - Loads `get_user_by_id(session["user_id"])` and redirects to
      `/login` if the user no longer exists (mirrors `profile()` and
      both export routes — defensive but consistent).
    - Calls the four new query helpers (see below) to gather:
      - `kpi_stats` (in-range total, in-range avg/day, all-time
        highest month, this-vs-last-month delta)
      - `monthly_trend` — fixed 12-month series, always all-time
      - `weekday_breakdown` — in-range
      - `top_expenses` — in-range, capped at 5
    - Passes them all to `render_template("analytics.html", ...)`.
- `database/queries.py`:
  - Add `get_monthly_trend(user_id, months=12)` — returns
    a list of `{"month": "YYYY-MM", "label": "May", "amount": float}`
    dicts for the last `months` calendar months ending with the current
    month. Months with zero spend are still present in the list with
    `amount = 0.0`. Always all-time scoped to `user_id` — no
    `date_from` / `date_to` parameters.
  - Add `get_weekday_breakdown(user_id, date_from=None, date_to=None)`
    — returns a list of seven `{"weekday": "Mon", "amount": float}`
    dicts in fixed Mon→Sun order. Days with zero spend are present
    with `amount = 0.0`. Follows the same both-or-neither
    `date_from` / `date_to` contract as the other Step-6 helpers.
  - Add `get_top_expenses(user_id, limit=5, date_from=None, date_to=None)`
    — returns the `limit` largest single expenses for the user as
    `{"id", "date", "description", "category", "amount"}` dicts ordered
    by `amount DESC, date DESC`. Same date-range contract as above.
  - Add `get_period_comparison(user_id, today)` — returns
    `{"this_month_total", "last_month_total", "delta", "pct_change"}`
    for the calendar month containing `today` vs the prior calendar
    month. `pct_change` is `None` (not `inf`) when `last_month_total`
    is zero — the template renders that case as `—`. The `today`
    argument is injected so tests can pass a fixed date.
  - Add `get_highest_spending_month(user_id)` — returns
    `{"month": "YYYY-MM", "label": "March 2026", "amount": float}` for
    the single calendar month with the highest spend across the user's
    entire history, or `None` if the user has no expenses.
- `templates/analytics.html` — replace the Coming Soon markup with the
  layout described above.
- `static/css/style.css` — add a new `Analytics` section near the
  existing `Landing — coming-soon` block (which can stay; nothing else
  references it yet, and removing it is out of scope). New styles:
  - `.analytics-section`, `.analytics-inner`, `.analytics-header`
    (mirror the profile equivalents)
  - `.kpi-grid` — 4-column grid that collapses to 2 columns under
    768px and 1 column under 480px
  - `.kpi-card`, `.kpi-label`, `.kpi-value`, `.kpi-delta--up`
    (red — higher spend, bad) and `.kpi-delta--down` (green — lower
    spend, good)
  - `.trend-chart` (12 columns), `.trend-bar`, `.trend-bar--peak`,
    `.trend-month-label`, `.trend-axis-line` (faint horizontal
    baseline)
  - `.weekday-chart` — reuses the existing `.category-breakdown` bar
    pattern; if a new modifier is needed, add `.bar--weekday`.
  - `.top-expenses-table` — same look as the existing recent-
    transactions table on the profile.
- `templates/base.html` — no changes (the nav link already exists).

## Files to create
None.

## New dependencies
No new dependencies. All chart rendering is plain SVG / CSS / vanilla JS.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`.
- Parameterised queries only — bind `user_id` and date params via `?`
  placeholders. Reuse the existing
  `where = "WHERE user_id = ?"` / `params = [user_id]` pattern. Never
  string-format dates into SQL.
- Use SQLite's `strftime('%Y-%m', date)` for monthly grouping and
  `strftime('%w', date)` (0 = Sun, 1 = Mon … 6 = Sat) for the weekday
  grouping — both are built-in, no Python-side date math required for
  the SQL.
- For the monthly trend, run a single `GROUP BY strftime('%Y-%m', date)`
  query, then in Python build the full 12-month skeleton (so months
  with no spend still appear with `amount = 0.0`). Do not call the DB
  in a loop.
- Passwords hashed with werkzeug (rule applies to any new code
  touching credentials — none here).
- Use CSS variables — never hardcode hex values. The KPI delta
  colours must come from the existing `--accent` family plus the
  warning/red token used for the "+12% vs last" subtext on the
  landing-page mock card (already in `:root`). If a new red token is
  needed, add it to `:root` rather than inlining a hex value.
- All templates extend `base.html`.
- **Ownership enforcement is mandatory.** Every new query helper MUST
  filter by `user_id = ?`. A user must never see another user's data
  in any analytics panel.
- The `/analytics` view is `GET` only and read-only — no DB writes.
- Bar heights / widths must be computed server-side (passed in the
  context) or via inline `style="height: {{ pct }}%"` rules — no
  JavaScript bar-sizing. Lucide icon hydration via
  `lucide.createIcons()` already runs in `base.html` and covers the
  new icons too — do not duplicate that call.
- Currency renders as `₹` everywhere (matches the rest of the app).
  Use the existing `{{ "{:,.0f}".format(amount) }}` pattern for the
  KPI numbers; use the trailing-decimal pattern from the recent-
  transactions table for the Top Expenses table.
- No inline `<script>` blocks beyond what `base.html` already loads.
  Any small interactivity (e.g. a hover tooltip on the trend bars)
  goes in `static/js/main.js`, gated by a feature check (only run
  when an element with the target class is present).
- The analytics filter UI must mirror the profile filter UI exactly
  — same pills, same custom-range form, same labels — so users have
  a single mental model. Reuse the existing styles; do not redefine
  them.
- The monthly trend chart is intentionally *not* affected by the
  date filter — it always shows the most recent 12 months end-aligned
  to today. State this in a small caption under the chart (e.g.
  "Last 12 months — all categories").
- All other panels (KPIs except "highest month", weekday breakdown,
  top expenses) respect the active filter.
- Empty-state copy must be neutral: "No expenses in this range." —
  not jokey, matches the tone of the export empty PDF / xlsx.
- No charting libraries (no Chart.js, no D3, no Recharts, nothing).
  Charts are SVG or `<div>`-based bars styled via `style.css`.

## Definition of done
- [ ] `GET /analytics` while logged out redirects to `/login`
- [ ] `GET /analytics` while logged in renders the new layout — no
      "Coming Soon" copy remains anywhere on the page
- [ ] Headline KPI strip shows: total in range, average per day in
      range, highest spending month (all-time), and this-month-vs-
      last-month delta with correct `+₹X (+Y%)` / `−₹X (−Y%)` sign and
      colour
- [ ] Monthly trend bar chart shows exactly 12 bars, end-aligned to
      the current month, with month labels under each bar; months
      with no spend show as a zero-height bar (or a thin baseline)
- [ ] The tallest bar in the monthly trend is visually distinguished
      (accent colour) from the others
- [ ] Weekday breakdown shows seven bars in Mon → Sun order, each
      with the weekday label and total spend; zero-spend days show
      with width 0% (not absent)
- [ ] Top expenses table lists up to 5 rows, ordered by amount desc;
      each row links to the corresponding edit page
- [ ] Date filter (presets + custom range) on the page behaves
      identically to `/profile` — picking "This Month" updates the
      KPI strip, the weekday breakdown, and the top expenses; the
      monthly trend stays fixed at the last 12 months
- [ ] Invalid date pairs (`date_from > date_to`, garbage values) are
      handled the same way as on `/profile`: the filter is dropped and
      an error is flashed; the page still renders
- [ ] All amounts render as `₹` and use the same number formatting
      as the rest of the app
- [ ] Cross-user isolation: a second seeded user's expenses never
      appear in any panel for the logged-in user
- [ ] Page is responsive — KPI grid collapses to 2 cols under 768px
      and 1 col under 480px; chart panels remain readable on mobile
- [ ] No hardcoded hex values anywhere in the new CSS — every colour
      comes from a `:root` token
- [ ] No JS frameworks or charting libraries added; bundle still
      contains only `static/js/main.js`
- [ ] `pytest` passes for the new analytics query helpers and route
      tests (file: `tests/test_11-analytics.py`)
