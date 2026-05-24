# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Project Overview

Spendly is a personal expense tracking web app built with Flask. It is a step-by-step student project. All core features through Step 11 (analytics) are now implemented. The app tracks expenses in Indian Rupees.

## 2. Architecture

```
expense-tracker/
├── app.py                  # Flask app — all routes live here (single file, no blueprints)
├── requirements.txt        # Pinned Python deps
├── database/
│   ├── __init__.py         # Empty
│   ├── db.py               # DB layer — exposes get_db(), init_db(), seed_db()
│   └── queries.py          # All SQL query functions + CATEGORIES constant
├── templates/
│   ├── base.html           # Master layout — navbar, footer, asset loading
│   ├── landing.html        # Homepage with hero, features, CTA, video modal
│   ├── login.html          # Login form
│   ├── register.html       # Registration form
│   ├── profile.html        # Dashboard — stats, transactions, category breakdown, filters
│   ├── analytics.html      # Analytics — monthly trend, weekday breakdown, top expenses
│   ├── add_expense.html    # Add expense form
│   ├── edit_expense.html   # Edit expense form
│   ├── terms.html          # Terms and Conditions static page
│   └── privacy.html        # Privacy Policy static page
└── static/
    ├── css/
    │   └── style.css       # Single stylesheet — all styles, design tokens in :root
    ├── fonts/
    │   ├── DejaVuSans.ttf       # Used by ReportLab for PDF exports (rupee glyph)
    │   └── DejaVuSans-Bold.ttf
    └── js/
        └── main.js         # Vanilla JS
```

- **Routes** go in `app.py`. There are no blueprints; everything is in one file.
- **Templates** must extend `base.html` using Jinja2 block inheritance (`{% block title %}`, `{% block content %}`, `{% block head %}`, `{% block scripts %}`).
- **Styles** go in `static/css/style.css`. Design tokens (colors, fonts, radii, widths) are CSS custom properties in `:root`.
- **JavaScript** goes in `static/js/main.js` or inline via the `{% block scripts %}` block.
- **Database** file is `expense_tracker.db` (SQLite, gitignored). `database/db.py` exposes `get_db()` (connection with `row_factory` + foreign keys), `init_db()` (CREATE TABLE IF NOT EXISTS), `seed_db()` (sample data). All query logic lives in `database/queries.py`.
- **CSRF protection** is hand-rolled in `app.py` — a per-session token is auto-injected into every Jinja context as `csrf_token()`. Every POST form must include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
- **Auth guard** — use the `@login_required` decorator (defined in `app.py`) on any route that requires a logged-in user.

## 3. Code Style

- **CSS**: Use the existing custom properties (`--ink`, `--paper`, `--accent`, `--border`, `--radius-sm/md/lg`, etc.) — do not introduce raw color or font values. Comment-delimited sections with dashed-line banners for grouping.
- **Fonts**: DM Serif Display for headings (`var(--font-display)`), DM Sans for body text (`var(--font-body)`). Both loaded from Google Fonts in `base.html`.
- **HTML/Templates**: Extend `base.html`. Use `url_for()` for all internal links and static assets. Class names are lowercase-hyphenated (BEM-ish but not strict BEM).
- **Python**: Standard Flask patterns. Routes are decorated functions returning `render_template()` or redirects. No stub routes remain.

## 4. Tech Constraints

- **Python 3.9** with a local venv at `.venv/`.
- **Flask 3.1.3** / **Werkzeug 3.1.6** / **gunicorn 23.0.0** — versions are pinned in `requirements.txt`.
- **reportlab 4.2.5** / **openpyxl 3.1.5** — used for PDF and Excel expense exports.
- **No JS frameworks or libraries** — all interactivity must be vanilla JavaScript.
- **No CSS frameworks** — everything is hand-written in `style.css`.
- **SQLite** for the database — no ORM, no external DB server.
- **No build tools** — no bundler, no preprocessor, no TypeScript. Files are served as-is by Flask.

## 5. Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the dev server (port 5001, debug mode)
python app.py

# Run tests
pytest
```

## 6. Implemented Routes

All routes are fully implemented. No stubs remain.

| Route | View function | Auth | Notes |
|---|---|---|---|
| `GET /` | `landing()` | No | Redirects to `/profile` if logged in |
| `GET /register` | `register()` | No | |
| `POST /register` | `register()` | No | Creates user, redirects to login |
| `GET /login` | `login()` | No | |
| `POST /login` | `login()` | No | Sets session, redirects to landing |
| `GET /logout` | `logout()` | No | Clears session |
| `GET /profile` | `profile()` | Yes | Dashboard with stats, transactions, date filters |
| `GET /analytics` | `analytics()` | Yes | Monthly trend, weekday breakdown, top expenses |
| `GET /expenses/add` | `add_expense()` | Yes | |
| `POST /expenses/add` | `add_expense()` | Yes | |
| `GET /expenses/<int:expense_id>/edit` | `edit_expense(expense_id)` | Yes | |
| `POST /expenses/<int:expense_id>/edit` | `edit_expense(expense_id)` | Yes | |
| `POST /expenses/<int:expense_id>/delete` | `delete_expense(expense_id)` | Yes | DELETE is POST only (no GET) |
| `GET /expenses/export/pdf` | `export_expenses_pdf()` | Yes | Accepts `date_from`/`date_to` query params |
| `GET /expenses/export/xlsx` | `export_expenses_xlsx()` | Yes | Accepts `date_from`/`date_to` query params |
| `GET /terms` | `terms()` | No | |
| `GET /privacy` | `privacy()` | No | |

## 7. Warnings and Things to Avoid

- **Do not add JS frameworks or libraries** (React, jQuery, Alpine, etc.). The project explicitly requires vanilla JS only.
- **Do not add CSS frameworks** (Tailwind, Bootstrap, etc.). All styles go in `style.css` using the existing design token system.
- **Do not hardcode colors or fonts** — always use the CSS custom properties from `:root`.
- **Do not split `app.py` into blueprints** — the project uses a single-file Flask app by design.
- **Do not use an ORM** — the database layer is raw SQLite via Python's `sqlite3` module.
- **Do not introduce build tools** — no bundlers, transpilers, or preprocessors.
- **Do not commit `expense_tracker.db`**, `.env`, or anything in `.venv/` — these are gitignored.
- **SECRET_KEY must be set** via the `SECRET_KEY` environment variable in production — the app raises `RuntimeError` on startup if it is missing when `FLASK_ENV=production`.
- **Delete is POST-only** — `DELETE /expenses/<id>/delete` does not accept GET. Confirmation modals must submit a `<form method="POST">`.
- **All POST forms need a CSRF token** — include `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` in every form, or the request will be rejected with HTTP 400.
