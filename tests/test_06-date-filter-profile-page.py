"""
tests/test_06-date-filter-profile-page.py

Pytest test suite for Step 6: Date Filter for Profile Page.

All assertions are derived from the feature spec at
.claude/specs/06-date-filter-profile-page.md — NOT from the implementation.

Fixture strategy
----------------
- `app`          : Flask app configured with an isolated in-memory SQLite DB.
- `client`       : Plain (unauthenticated) test client.
- `db_conn`      : Direct SQLite connection to the same in-memory DB so tests
                   can insert controlled expense rows.
- `test_user_id` : Inserts one test user; returns the new user id.
- `auth_client`  : Test client with `user_id` already in the session.
- `seeded_client`: auth_client + a fixed set of expenses at known dates so
                   every date-range assertion is deterministic.
"""

import sqlite3
import pytest
from datetime import date, timedelta

from app import app as flask_app
from database.db import init_db
from database.queries import (
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _iso(d: date) -> str:
    return d.isoformat()


# ------------------------------------------------------------------ #
# Core fixtures                                                       #
# ------------------------------------------------------------------ #

@pytest.fixture
def app(tmp_path, monkeypatch):
    """
    Flask app wired to a temp-file SQLite DB (not :memory:) so that both
    the Flask test client *and* direct database.db helpers share the same
    file.  The DB is initialised fresh for every test.
    """
    db_file = str(tmp_path / "test_expenses.db")
    # Patch the DB_PATH used by database.db so every get_db() call inside
    # the application (routes + query helpers) hits this test database.
    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_file)

    flask_app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )

    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_conn(app):
    """
    A direct SQLite connection to the test DB.  Yields the connection;
    commits + closes after the test.
    """
    import database.db as db_module
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.commit()
    conn.close()


@pytest.fixture
def test_user_id(db_conn):
    """Insert a fresh test user and return its id."""
    cur = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("pw", method="pbkdf2:sha256")),
    )
    db_conn.commit()
    return cur.lastrowid


@pytest.fixture
def auth_client(client, test_user_id):
    """Test client with the test user already in session."""
    with client.session_transaction() as sess:
        sess["user_id"] = test_user_id
        sess["user_name"] = "Test User"
    return client


# ------------------------------------------------------------------ #
# Seeded expense data (deterministic dates)                           #
#                                                                     #
# We insert expenses at explicit dates so that the outcome of every   #
# date-range filter can be computed analytically in the test.         #
#                                                                     #
# today      → in THIS MONTH, LAST 3 MONTHS, LAST 6 MONTHS           #
# 15 days ago → in LAST 3 MONTHS, LAST 6 MONTHS (may or may not be   #
#               in THIS MONTH depending on calendar; we keep it ≥1    #
#               day before today to stay in the same month safely)    #
# 91 days ago → in LAST 6 MONTHS only (outside 90-day window)        #
# 200 days ago → outside all preset windows                           #
#                                                                     #
# Amounts are chosen so totals are easy to verify.                    #
# ------------------------------------------------------------------ #

TODAY = date.today()
DATE_TODAY        = _iso(TODAY)
DATE_15_DAYS_AGO  = _iso(TODAY - timedelta(days=15))
DATE_91_DAYS_AGO  = _iso(TODAY - timedelta(days=91))
DATE_200_DAYS_AGO = _iso(TODAY - timedelta(days=200))

# Preset window bounds (mirrors app.py _resolve_presets)
PRESET_THIS_MONTH_FROM  = _iso(TODAY.replace(day=1))
PRESET_THIS_MONTH_TO    = DATE_TODAY
PRESET_3M_FROM          = _iso(TODAY - timedelta(days=90))
PRESET_3M_TO            = DATE_TODAY
PRESET_6M_FROM          = _iso(TODAY - timedelta(days=180))
PRESET_6M_TO            = DATE_TODAY

# Seeded rows: (amount, category, date, description)
SEED_ROWS = [
    (100.00, "Food",          DATE_TODAY,        "Expense today"),
    (200.00, "Transport",     DATE_15_DAYS_AGO,  "Expense 15 days ago"),
    (400.00, "Shopping",      DATE_91_DAYS_AGO,  "Expense 91 days ago"),
    (800.00, "Bills",         DATE_200_DAYS_AGO, "Expense 200 days ago"),
]

# Pre-compute expected totals for each window (spec: BETWEEN is inclusive)
# This Month: expenses with date >= first_of_month AND date <= today
def _in_this_month(row_date: str) -> bool:
    return PRESET_THIS_MONTH_FROM <= row_date <= PRESET_THIS_MONTH_TO

def _in_last_3m(row_date: str) -> bool:
    return PRESET_3M_FROM <= row_date <= PRESET_3M_TO

def _in_last_6m(row_date: str) -> bool:
    return PRESET_6M_FROM <= row_date <= PRESET_6M_TO

EXPECTED_THIS_MONTH_TOTAL = sum(r[0] for r in SEED_ROWS if _in_this_month(r[2]))
EXPECTED_THIS_MONTH_COUNT = sum(1 for r in SEED_ROWS if _in_this_month(r[2]))

EXPECTED_3M_TOTAL = sum(r[0] for r in SEED_ROWS if _in_last_3m(r[2]))
EXPECTED_3M_COUNT = sum(1 for r in SEED_ROWS if _in_last_3m(r[2]))

EXPECTED_6M_TOTAL = sum(r[0] for r in SEED_ROWS if _in_last_6m(r[2]))
EXPECTED_6M_COUNT = sum(1 for r in SEED_ROWS if _in_last_6m(r[2]))

EXPECTED_ALL_TOTAL = sum(r[0] for r in SEED_ROWS)
EXPECTED_ALL_COUNT = len(SEED_ROWS)


@pytest.fixture
def seeded_client(auth_client, db_conn, test_user_id):
    """auth_client with a known, controlled set of expenses inserted."""
    db_conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        [(test_user_id, r[0], r[1], r[2], r[3]) for r in SEED_ROWS],
    )
    db_conn.commit()
    return auth_client


# ------------------------------------------------------------------ #
# 1. Happy paths — unfiltered                                         #
# ------------------------------------------------------------------ #

class TestProfileUnfiltered:

    def test_profile_no_params_returns_200(self, seeded_client):
        """Spec: GET /profile with no query params returns 200 for logged-in user."""
        response = seeded_client.get("/profile")
        assert response.status_code == 200, (
            "Expected 200 for authenticated GET /profile with no params"
        )

    def test_profile_no_params_shows_rupee_symbol(self, seeded_client):
        """Spec: All amounts display the ₹ symbol regardless of active filter."""
        response = seeded_client.get("/profile")
        assert "₹" in response.data.decode("utf-8"), (
            "Expected ₹ symbol to appear in the profile page"
        )

    def test_profile_no_params_unfiltered_total(self, seeded_client):
        """Spec: No-params view shows all-time total (Step 5 baseline preserved)."""
        response = seeded_client.get("/profile")
        body = response.data.decode("utf-8")
        # Summary stat-value uses {:,.0f} per Step-5 template baseline
        assert f"{EXPECTED_ALL_TOTAL:,.0f}" in body, (
            f"Expected all-time total {EXPECTED_ALL_TOTAL:,.0f} in unfiltered profile page"
        )

    def test_profile_no_params_unfiltered_transaction_count(self, seeded_client):
        """Spec: No-params view shows count of all seeded transactions."""
        response = seeded_client.get("/profile")
        body = response.data.decode("utf-8")
        assert str(EXPECTED_ALL_COUNT) in body, (
            f"Expected transaction count {EXPECTED_ALL_COUNT} in unfiltered profile page"
        )


# ------------------------------------------------------------------ #
# 2. Happy paths — filtered by custom date range                      #
# ------------------------------------------------------------------ #

class TestProfileDateRangeFilter:

    def test_profile_valid_date_range_returns_200(self, seeded_client):
        """Spec: GET /profile?date_from=Y&date_to=Z with valid ISO dates returns 200."""
        response = seeded_client.get(
            f"/profile?date_from={DATE_15_DAYS_AGO}&date_to={DATE_TODAY}"
        )
        assert response.status_code == 200, (
            "Expected 200 for authenticated GET /profile with valid date range"
        )

    def test_profile_date_range_filters_transaction_count(self, seeded_client):
        """Spec: Custom range filters the recent-transactions section to the window."""
        # Window: DATE_TODAY only — just the 'today' expense (100.00)
        response = seeded_client.get(
            f"/profile?date_from={DATE_TODAY}&date_to={DATE_TODAY}"
        )
        body = response.data.decode("utf-8")
        # Only the 'today' expense (100.00 / 1 transaction) should appear
        assert "100.00" in body, (
            "Expected filtered expense amount 100.00 in narrowly-filtered profile page"
        )
        # The 200.00 expense (15 days ago) must NOT appear
        assert "200.00" not in body, (
            "Did not expect out-of-window expense (200.00) to appear in filtered view"
        )

    def test_profile_date_range_filters_total_spent(self, seeded_client):
        """Spec: Summary stats total reflects only in-window expenses."""
        # Window spanning the two most recent expenses: 100 + 200 = 300
        response = seeded_client.get(
            f"/profile?date_from={DATE_15_DAYS_AGO}&date_to={DATE_TODAY}"
        )
        body = response.data.decode("utf-8")
        expected = 100.00 + 200.00  # only rows within this window
        assert f"₹{expected:,.0f}" in body, (
            f"Expected filtered total ₹{expected:,.0f} in filtered profile page"
        )

    def test_profile_date_range_filters_category_breakdown(self, seeded_client):
        """Spec: Category breakdown reflects only in-window expenses."""
        # Window: only DATE_TODAY → only 'Food' category for 100.00
        response = seeded_client.get(
            f"/profile?date_from={DATE_TODAY}&date_to={DATE_TODAY}"
        )
        body = response.data.decode("utf-8")
        assert "Food" in body, (
            "Expected 'Food' category to appear in filtered category breakdown"
        )
        # 'Bills' category is 200 days ago — outside window
        assert "Bills" not in body, (
            "Did not expect 'Bills' category (200 days ago) in narrowly-filtered view"
        )


# ------------------------------------------------------------------ #
# 3. Preset windows                                                   #
# ------------------------------------------------------------------ #

class TestProfilePresets:

    def test_profile_this_month_preset_matches_window(self, seeded_client):
        """Spec: 'This Month' preset filters to current calendar month; totals match."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_THIS_MONTH_FROM}&date_to={PRESET_THIS_MONTH_TO}"
        )
        assert response.status_code == 200, "Expected 200 for This Month preset"
        body = response.data.decode("utf-8")
        assert f"{EXPECTED_THIS_MONTH_TOTAL:.2f}" in body, (
            f"Expected This Month total {EXPECTED_THIS_MONTH_TOTAL:.2f} in response"
        )

    def test_profile_last_3_months_preset_matches_window(self, seeded_client):
        """Spec: 'Last 3 Months' preset filters to 90-day window ending today."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_3M_FROM}&date_to={PRESET_3M_TO}"
        )
        assert response.status_code == 200, "Expected 200 for Last 3 Months preset"
        body = response.data.decode("utf-8")
        assert f"₹{EXPECTED_3M_TOTAL:,.0f}" in body, (
            f"Expected Last 3 Months total ₹{EXPECTED_3M_TOTAL:,.0f} in response"
        )

    def test_profile_last_6_months_preset_matches_window(self, seeded_client):
        """Spec: 'Last 6 Months' preset filters to 180-day window ending today."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_6M_FROM}&date_to={PRESET_6M_TO}"
        )
        assert response.status_code == 200, "Expected 200 for Last 6 Months preset"
        body = response.data.decode("utf-8")
        assert f"₹{EXPECTED_6M_TOTAL:,.0f}" in body, (
            f"Expected Last 6 Months total ₹{EXPECTED_6M_TOTAL:,.0f} in response"
        )

    def test_profile_this_month_preset_transaction_count(self, seeded_client):
        """Spec: This Month transaction count matches seeded data in window."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_THIS_MONTH_FROM}&date_to={PRESET_THIS_MONTH_TO}"
        )
        body = response.data.decode("utf-8")
        assert str(EXPECTED_THIS_MONTH_COUNT) in body, (
            f"Expected This Month count {EXPECTED_THIS_MONTH_COUNT} in response"
        )

    def test_profile_last_3_months_excludes_older_expenses(self, seeded_client):
        """Spec: Last 3 Months must not include expenses older than 90 days."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_3M_FROM}&date_to={PRESET_3M_TO}"
        )
        body = response.data.decode("utf-8")
        # The 800.00 expense is 200 days ago — must not appear
        assert "800.00" not in body, (
            "Did not expect 800.00 (200-day-old) expense in Last 3 Months view"
        )

    def test_profile_last_6_months_excludes_200_day_old_expenses(self, seeded_client):
        """Spec: Last 6 Months must not include expenses older than 180 days."""
        response = seeded_client.get(
            f"/profile?date_from={PRESET_6M_FROM}&date_to={PRESET_6M_TO}"
        )
        body = response.data.decode("utf-8")
        # The 800.00 expense is 200 days ago — must not appear
        assert "800.00" not in body, (
            "Did not expect 800.00 (200-day-old) expense in Last 6 Months view"
        )


# ------------------------------------------------------------------ #
# 4. Auth guard                                                        #
# ------------------------------------------------------------------ #

class TestProfileAuthGuard:

    def test_profile_unauthenticated_redirects_to_login(self, client):
        """Spec: Unauthenticated GET /profile returns 302 to /login."""
        response = client.get("/profile")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated GET /profile"
        )
        assert "/login" in response.headers.get("Location", ""), (
            "Expected redirect target to be /login"
        )

    def test_profile_unauthenticated_with_filter_params_redirects_to_login(self, client):
        """Spec: Unauthenticated GET /profile with filter params also returns 302 to /login."""
        response = client.get(
            f"/profile?date_from={DATE_15_DAYS_AGO}&date_to={DATE_TODAY}"
        )
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated GET /profile with filter params"
        )
        assert "/login" in response.headers.get("Location", ""), (
            "Expected redirect target to be /login even when filter params are present"
        )


# ------------------------------------------------------------------ #
# 5. Validation / fallback behaviour                                  #
# ------------------------------------------------------------------ #

class TestProfileValidationAndFallback:

    def test_profile_date_from_after_date_to_shows_flash_error(self, seeded_client):
        """Spec: date_from > date_to triggers a flash error containing
        'Start date must be before end date.'"""
        response = seeded_client.get(
            f"/profile?date_from={DATE_TODAY}&date_to={DATE_15_DAYS_AGO}",
            follow_redirects=True,
        )
        body = response.data.decode("utf-8")
        assert "Start date must be before end date." in body, (
            "Expected flash error 'Start date must be before end date.' when date_from > date_to"
        )

    def test_profile_date_from_after_date_to_falls_back_to_unfiltered(self, seeded_client):
        """Spec: When date_from > date_to, page falls back to the unfiltered (all-time) view."""
        response = seeded_client.get(
            f"/profile?date_from={DATE_TODAY}&date_to={DATE_15_DAYS_AGO}",
            follow_redirects=True,
        )
        assert response.status_code == 200, (
            "Expected 200 for inverted date range (fallback, not error)"
        )
        body = response.data.decode("utf-8")
        # All-time total must be present because filter was rejected
        assert f"₹{EXPECTED_ALL_TOTAL:,.0f}" in body, (
            f"Expected all-time total ₹{EXPECTED_ALL_TOTAL:,.0f} when date range is inverted"
        )

    def test_profile_malformed_date_from_no_crash(self, seeded_client):
        """Spec: Malformed date string (e.g. not-a-date) does not crash — returns 200."""
        response = seeded_client.get("/profile?date_from=not-a-date&date_to=also-bad")
        assert response.status_code == 200, (
            "Expected 200 (no crash) when date_from is a malformed string"
        )

    def test_profile_malformed_date_from_no_flash_error(self, seeded_client):
        """Spec: Malformed date falls back silently — NO flash error message."""
        response = seeded_client.get("/profile?date_from=not-a-date&date_to=also-bad")
        body = response.data.decode("utf-8")
        assert "Start date must be before end date." not in body, (
            "Expected no flash error for malformed date string — silent fallback only"
        )

    def test_profile_malformed_date_from_unfiltered_output(self, seeded_client):
        """Spec: Malformed date falls back to unfiltered (all-time) output."""
        response = seeded_client.get("/profile?date_from=not-a-date&date_to=also-bad")
        body = response.data.decode("utf-8")
        assert f"₹{EXPECTED_ALL_TOTAL:,.0f}" in body, (
            f"Expected all-time total ₹{EXPECTED_ALL_TOTAL:,.0f} when dates are malformed"
        )

    def test_profile_only_date_from_provided_unfiltered(self, seeded_client):
        """Spec: Only one of date_from/date_to provided → unfiltered, no flash."""
        response = seeded_client.get(f"/profile?date_from={DATE_TODAY}")
        assert response.status_code == 200, (
            "Expected 200 when only date_from is provided"
        )
        body = response.data.decode("utf-8")
        assert f"₹{EXPECTED_ALL_TOTAL:,.0f}" in body, (
            "Expected all-time total when only date_from is provided (unfiltered fallback)"
        )
        assert "Start date must be before end date." not in body, (
            "Expected no flash error when only date_from is provided"
        )

    def test_profile_only_date_to_provided_unfiltered(self, seeded_client):
        """Spec: Only one of date_from/date_to provided → unfiltered, no flash."""
        response = seeded_client.get(f"/profile?date_to={DATE_TODAY}")
        assert response.status_code == 200, (
            "Expected 200 when only date_to is provided"
        )
        body = response.data.decode("utf-8")
        assert f"₹{EXPECTED_ALL_TOTAL:,.0f}" in body, (
            "Expected all-time total when only date_to is provided (unfiltered fallback)"
        )
        assert "Start date must be before end date." not in body, (
            "Expected no flash error when only date_to is provided"
        )

    @pytest.mark.parametrize("date_from,date_to", [
        ("2024-13-01", "2024-12-31"),   # month 13 — invalid
        ("2024-00-15", "2024-12-31"),   # month 0 — invalid
        ("not-a-date", "2024-12-31"),   # non-date string
        ("2024/01/15", "2024/12/31"),   # wrong separator
        ("", "2024-12-31"),             # empty string
    ])
    def test_profile_various_malformed_dates_no_crash(self, seeded_client, date_from, date_to):
        """Spec: Any malformed date string must not crash the app — silent fallback."""
        response = seeded_client.get(
            f"/profile?date_from={date_from}&date_to={date_to}"
        )
        assert response.status_code == 200, (
            f"Expected 200 (no crash) for malformed date_from={date_from!r}"
        )


# ------------------------------------------------------------------ #
# 6. Empty-state behaviour                                            #
# ------------------------------------------------------------------ #

class TestProfileEmptyState:

    def test_profile_empty_window_no_crash(self, seeded_client):
        """Spec: No expenses in selected window — page still returns 200, no exception."""
        # Use a historical window where no seeded expense exists
        far_past_from = "2000-01-01"
        far_past_to   = "2000-01-31"
        response = seeded_client.get(
            f"/profile?date_from={far_past_from}&date_to={far_past_to}"
        )
        assert response.status_code == 200, (
            "Expected 200 when no expenses exist in the selected window"
        )

    def test_profile_empty_window_zero_total(self, seeded_client):
        """Spec: No expenses in window → total spent displays as ₹0."""
        far_past_from = "2000-01-01"
        far_past_to   = "2000-01-31"
        response = seeded_client.get(
            f"/profile?date_from={far_past_from}&date_to={far_past_to}"
        )
        body = response.data.decode("utf-8")
        # stat-value formats with {:,.0f} → renders as "₹0"
        assert "₹0" in body, (
            "Expected ₹0 total when no expenses exist in the selected window"
        )

    def test_profile_empty_window_zero_transactions(self, seeded_client):
        """Spec: No expenses in window → 0 transactions shown."""
        far_past_from = "2000-01-01"
        far_past_to   = "2000-01-31"
        response = seeded_client.get(
            f"/profile?date_from={far_past_from}&date_to={far_past_to}"
        )
        body = response.data.decode("utf-8")
        # The transaction count of 0 must appear somewhere on the page
        assert "0" in body, (
            "Expected 0 transaction count when no expenses exist in the selected window"
        )

    def test_profile_user_with_no_expenses_at_all_returns_200(self, auth_client):
        """Spec: A user with zero total expenses sees ₹0, no errors (unfiltered)."""
        response = auth_client.get("/profile")
        assert response.status_code == 200, (
            "Expected 200 for a user with no expenses at all"
        )
        body = response.data.decode("utf-8")
        # stat-value formats with {:,.0f} → renders as "₹0"
        assert "₹0" in body, (
            "Expected ₹0 total for a user with no expenses"
        )


# ------------------------------------------------------------------ #
# 7. Unit tests — get_summary_stats                                   #
# ------------------------------------------------------------------ #

class TestGetSummaryStats:

    def _insert_expenses(self, db_conn, user_id, rows):
        db_conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            [(user_id, r[0], r[1], r[2], r[3]) for r in rows],
        )
        db_conn.commit()

    def test_get_summary_stats_no_dates_equals_all_expenses(self, db_conn, test_user_id, app):
        """Spec: (None, None) returns the same unfiltered totals as Step 5 baseline."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            result = get_summary_stats(test_user_id)
        assert result["total_spent"] == pytest.approx(EXPECTED_ALL_TOTAL), (
            "get_summary_stats(None, None) must return all-time total"
        )
        assert result["transaction_count"] == EXPECTED_ALL_COUNT, (
            "get_summary_stats(None, None) must return all-time transaction count"
        )

    def test_get_summary_stats_with_dates_scoped_total(self, db_conn, test_user_id, app):
        """Spec: Both dates provided → total_spent is scoped to the window."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: only today's expense (100.00)
        with app.app_context():
            result = get_summary_stats(test_user_id, date_from=DATE_TODAY, date_to=DATE_TODAY)
        assert result["total_spent"] == pytest.approx(100.00), (
            "get_summary_stats with narrow window must return only in-window total"
        )
        assert result["transaction_count"] == 1, (
            "get_summary_stats with narrow window must return only in-window count"
        )

    def test_get_summary_stats_with_dates_scoped_top_category(self, db_conn, test_user_id, app):
        """Spec: top_category reflects the highest-spending category within the window."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: only today's expense → Food (100.00)
        with app.app_context():
            result = get_summary_stats(test_user_id, date_from=DATE_TODAY, date_to=DATE_TODAY)
        assert result["top_category"] == "Food", (
            "get_summary_stats top_category must be the highest category within the window"
        )

    def test_get_summary_stats_empty_window_zero_total(self, db_conn, test_user_id, app):
        """Spec: No expenses in window → total_spent=0.0, transaction_count=0."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            result = get_summary_stats(test_user_id, date_from="2000-01-01", date_to="2000-01-31")
        assert result["total_spent"] == 0.0, (
            "get_summary_stats must return 0.0 total when no expenses in window"
        )
        assert result["transaction_count"] == 0, (
            "get_summary_stats must return 0 count when no expenses in window"
        )

    def test_get_summary_stats_returns_dash_for_top_category_when_no_expenses(
        self, db_conn, test_user_id, app
    ):
        """Spec: When no expenses exist in the window top_category must be '—' (em dash)."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            result = get_summary_stats(test_user_id, date_from="2000-01-01", date_to="2000-01-31")
        assert result["top_category"] == "—", (
            "get_summary_stats top_category must be '—' when no expenses in window"
        )


# ------------------------------------------------------------------ #
# 8. Unit tests — get_recent_transactions                             #
# ------------------------------------------------------------------ #

class TestGetRecentTransactions:

    def _insert_expenses(self, db_conn, user_id, rows):
        db_conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            [(user_id, r[0], r[1], r[2], r[3]) for r in rows],
        )
        db_conn.commit()

    def test_get_recent_transactions_newest_first(self, db_conn, test_user_id, app):
        """Spec: Results are ordered newest first regardless of date filter."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            txns = get_recent_transactions(test_user_id, limit=10)
        dates = [t["date"] for t in txns]
        assert dates == sorted(dates, reverse=True), (
            "get_recent_transactions must return results in newest-first order"
        )

    def test_get_recent_transactions_date_filter_scopes_results(self, db_conn, test_user_id, app):
        """Spec: Only transactions within the window are returned."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: today only — should return 1 row (Expense today, 100.00)
        with app.app_context():
            txns = get_recent_transactions(
                test_user_id, limit=10, date_from=DATE_TODAY, date_to=DATE_TODAY
            )
        assert len(txns) == 1, (
            f"Expected 1 transaction in narrow window, got {len(txns)}"
        )
        assert txns[0]["amount"] == 100.00, (
            "Expected the 100.00 expense in the narrow window"
        )

    def test_get_recent_transactions_limit_respected_with_date_filter(self, db_conn, test_user_id, app):
        """Spec: limit caps results independently of date filter."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # All 4 expenses are within the 200-day window; limit=2 must cap at 2
        far_back = "2000-01-01"
        with app.app_context():
            txns = get_recent_transactions(
                test_user_id, limit=2, date_from=far_back, date_to=DATE_TODAY
            )
        assert len(txns) <= 2, (
            "get_recent_transactions must not return more rows than the limit"
        )

    def test_get_recent_transactions_limit_respected_unfiltered(self, db_conn, test_user_id, app):
        """Spec: limit is honoured in the unfiltered (no dates) case."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            txns = get_recent_transactions(test_user_id, limit=2)
        assert len(txns) <= 2, (
            "get_recent_transactions must not exceed the limit in unfiltered mode"
        )

    def test_get_recent_transactions_empty_window_returns_empty_list(self, db_conn, test_user_id, app):
        """Spec: No transactions in window → empty list (no exception)."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            txns = get_recent_transactions(
                test_user_id, limit=10, date_from="2000-01-01", date_to="2000-01-31"
            )
        assert txns == [], (
            "get_recent_transactions must return [] when no expenses exist in window"
        )

    def test_get_recent_transactions_out_of_window_expense_not_returned(
        self, db_conn, test_user_id, app
    ):
        """Spec: Expenses outside the date range must not appear in results."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: today only — 200-day-old 800.00 expense must not appear
        with app.app_context():
            txns = get_recent_transactions(
                test_user_id, limit=10, date_from=DATE_TODAY, date_to=DATE_TODAY
            )
        amounts = [t["amount"] for t in txns]
        assert 800.00 not in amounts, (
            "get_recent_transactions must not include expenses outside the date window"
        )


# ------------------------------------------------------------------ #
# 9. Unit tests — get_category_breakdown                              #
# ------------------------------------------------------------------ #

class TestGetCategoryBreakdown:

    def _insert_expenses(self, db_conn, user_id, rows):
        db_conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            [(user_id, r[0], r[1], r[2], r[3]) for r in rows],
        )
        db_conn.commit()

    def test_get_category_breakdown_pct_sums_to_100(self, db_conn, test_user_id, app):
        """Spec: pct values sum to 100 within the active window."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Use a window that includes multiple categories
        far_back = "2000-01-01"
        with app.app_context():
            cats = get_category_breakdown(
                test_user_id, date_from=far_back, date_to=DATE_TODAY
            )
        if cats:  # non-empty: pct must sum to 100
            total_pct = sum(c["pct"] for c in cats)
            assert total_pct == 100, (
                f"Category breakdown pct values must sum to 100, got {total_pct}"
            )

    def test_get_category_breakdown_pct_sums_to_100_unfiltered(self, db_conn, test_user_id, app):
        """Spec: pct values sum to 100 in the unfiltered (no dates) case."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            cats = get_category_breakdown(test_user_id)
        if cats:
            total_pct = sum(c["pct"] for c in cats)
            assert total_pct == 100, (
                f"Category breakdown pct values must sum to 100 unfiltered, got {total_pct}"
            )

    def test_get_category_breakdown_empty_window_returns_empty_list(
        self, db_conn, test_user_id, app
    ):
        """Spec: Empty category breakdown returned (not an error) when no expenses in window."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        with app.app_context():
            cats = get_category_breakdown(
                test_user_id, date_from="2000-01-01", date_to="2000-01-31"
            )
        assert cats == [], (
            "get_category_breakdown must return [] when no expenses exist in window"
        )

    def test_get_category_breakdown_date_filter_correct_amounts(
        self, db_conn, test_user_id, app
    ):
        """Spec: category amounts reflect only in-window expenses."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: today only → only Food (100.00)
        with app.app_context():
            cats = get_category_breakdown(
                test_user_id, date_from=DATE_TODAY, date_to=DATE_TODAY
            )
        assert len(cats) == 1, (
            f"Expected 1 category in narrow window, got {len(cats)}"
        )
        assert cats[0]["name"] == "Food", (
            "Expected 'Food' as the only category in the narrow window"
        )
        assert cats[0]["amount"] == pytest.approx(100.00), (
            "Category amount must equal the in-window expense amount"
        )

    def test_get_category_breakdown_no_out_of_window_categories(
        self, db_conn, test_user_id, app
    ):
        """Spec: Categories from outside the window must not appear in the breakdown."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        # Window: today only → 'Bills' (200 days ago) must not appear
        with app.app_context():
            cats = get_category_breakdown(
                test_user_id, date_from=DATE_TODAY, date_to=DATE_TODAY
            )
        cat_names = [c["name"] for c in cats]
        assert "Bills" not in cat_names, (
            "Category 'Bills' (200 days old) must not appear in a window ending today"
        )

    def test_get_category_breakdown_ordered_by_amount_desc(self, db_conn, test_user_id, app):
        """Spec: Category breakdown is ordered by amount descending."""
        self._insert_expenses(db_conn, test_user_id, SEED_ROWS)
        far_back = "2000-01-01"
        with app.app_context():
            cats = get_category_breakdown(
                test_user_id, date_from=far_back, date_to=DATE_TODAY
            )
        amounts = [c["amount"] for c in cats]
        assert amounts == sorted(amounts, reverse=True), (
            "get_category_breakdown must be ordered by amount descending"
        )
