# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Project Overview

Spendly is a personal expense tracking web app built with Flask. It is a step-by-step student project — the landing page, auth forms, and static pages are built out, but the core expense features and database layer are stubs awaiting implementation. The app tracks expenses in Indian Rupees.

## 2. Architecture

```
expense-tracker/
├── app.py                  # Flask app — all routes live here (single file, no blueprints)
├── requirements.txt        # Pinned Python deps (Flask, Werkzeug, pytest, pytest-flask)
├── database/
│   ├── __init__.py         # Empty
│   └── db.py               # DB layer (stub) — should expose get_db(), init_db(), seed_db()
├── templates/
│   ├── base.html           # Master layout — navbar, footer, asset loading
│   ├── landing.html        # Homepage with hero, features, CTA, video modal
│   ├── login.html          # Login form
│   ├── register.html       # Registration form
│   ├── terms.html          # Terms and Conditions static page
│   └── privacy.html        # Privacy Policy static page
└── static/
    ├── css/
    │   └── style.css       # Single stylesheet — all styles, design tokens in :root
    └── js/
        └── main.js         # Vanilla JS (currently minimal)
```

- **Routes** go in `app.py`. There are no blueprints; everything is in one file.
- **Templates** must extend `base.html` using Jinja2 block inheritance (`{% block title %}`, `{% block content %}`, `{% block head %}`, `{% block scripts %}`).
- **Styles** go in `static/css/style.css`. Design tokens (colors, fonts, radii, widths) are CSS custom properties in `:root`.
- **JavaScript** goes in `static/js/main.js` or inline via the `{% block scripts %}` block.
- **Database** file will be `expense_tracker.db` (SQLite, gitignored). The `database/db.py` stub expects three functions: `get_db()` (connection with `row_factory` + foreign keys), `init_db()` (CREATE TABLE IF NOT EXISTS), `seed_db()` (sample data).

## 3. Code Style

- **CSS**: Use the existing custom properties (`--ink`, `--paper`, `--accent`, `--border`, `--radius-sm/md/lg`, etc.) — do not introduce raw color or font values. Comment-delimited sections with dashed-line banners for grouping.
- **Fonts**: DM Serif Display for headings (`var(--font-display)`), DM Sans for body text (`var(--font-body)`). Both loaded from Google Fonts in `base.html`.
- **HTML/Templates**: Extend `base.html`. Use `url_for()` for all internal links and static assets. Class names are lowercase-hyphenated (BEM-ish but not strict BEM).
- **Python**: Standard Flask patterns. Routes are decorated functions returning `render_template()` or plain strings for stubs.

## 4. Tech Constraints

- **Python 3.9** with a local venv at `.venv/`.
- **Flask 3.1.3** / **Werkzeug 3.1.6** — versions are pinned in `requirements.txt`.
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

## 6. Implemented vs Stub Routes

**Implemented** (renders a template):
| Route | View function | Template |
|---|---|---|
| `GET /` | `landing()` | `landing.html` |
| `GET /register` | `register()` | `register.html` |
| `GET /login` | `login()` | `login.html` |
| `GET /terms` | `terms()` | `terms.html` |
| `GET /privacy` | `privacy()` | `privacy.html` |

**Stubs** (returns a placeholder string, not yet implemented):
| Route | View function | Step |
|---|---|---|
| `GET /logout` | `logout()` | Step 3 |
| `GET /profile` | `profile()` | Step 4 |
| `GET /expenses/add` | `add_expense()` | Step 7 |
| `GET /expenses/<int:id>/edit` | `edit_expense(id)` | Step 8 |
| `GET /expenses/<int:id>/delete` | `delete_expense(id)` | Step 9 |

The `database/db.py` file is also a stub — the database layer has not been implemented yet (Step 1).

## 7. Warnings and Things to Avoid

- **Do not add JS frameworks or libraries** (React, jQuery, Alpine, etc.). The project explicitly requires vanilla JS only.
- **Do not add CSS frameworks** (Tailwind, Bootstrap, etc.). All styles go in `style.css` using the existing design token system.
- **Do not hardcode colors or fonts** — always use the CSS custom properties from `:root`.
- **Do not split `app.py` into blueprints** — the project uses a single-file Flask app by design.
- **Do not use an ORM** — the database layer is raw SQLite via Python's `sqlite3` module.
- **Do not introduce build tools** — no bundlers, transpilers, or preprocessors.
- **Do not commit `expense_tracker.db`**, `.env`, or anything in `.venv/` — these are gitignored.
- **Preserve the step-by-step structure** — stub routes reference specific implementation steps. Don't implement a later step unless asked.
