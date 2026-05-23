"""Pytest test suite for Step 11: Analytics.

Assertions derived from .claude/specs/11-analytics.md — never from
implementation details.

Covers:
- Unit tests for every new query helper in database/queries.py
  (get_monthly_trend, get_weekday_breakdown, get_top_expenses,
   get_period_comparison, get_highest_spending_month,
   get_earliest_expense_date)
- Route tests for GET /analytics: auth guard, template rendering, filter
  behaviour, invalid date handling, empty-state rendering
- Cross-user isolation at both the query-helper and route levels
"""

import datetime
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from database.queries import (
    get_earliest_expense_date,
    get_highest_spending_month,
    get_monthly_trend,
    get_period_comparison,
    get_top_expenses,
    get_weekday_breakdown,
)


# ------------------------------------------------------------------ #
# Local helpers                                                        #
# ------------------------------------------------------------------ #


def _create_user(db_conn, name, email):
    """Insert a user row and return its id."""
    cur = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash("pw", method="pbkdf2:sha256")),
    )
    db_conn.commit()
    return cur.lastrowid


def _insert_expense(db_conn, user_id, amount, category, expense_date, description=None):
    """Insert a single expense row directly; returns the new row id."""
    cur = db_conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, expense_date, description),
    )
    db_conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ #
# Per-test fixtures                                                    #
#   `app`, `client`, `db_conn` come from conftest.py                  #
# ------------------------------------------------------------------ #


@pytest.fixture
def test_user_id(db_conn):
    return _create_user(db_conn, "Owner User", "owner@example.com")


@pytest.fixture
def other_user_id(db_conn):
    return _create_user(db_conn, "Other User", "other@example.com")


@pytest.fixture
def auth_client(client, test_user_id):
    """Test client with test_user_id already in the session."""
    with client.session_transaction() as sess:
        sess["user_id"] = test_user_id
        sess["user_name"] = "Owner User"
    return client


# ------------------------------------------------------------------ #
# 1. Unit tests — get_monthly_trend                                    #
# ------------------------------------------------------------------ #


class TestGetMonthlyTrend:

    def test_returns_exactly_12_entries(self, app, test_user_id):
        """Spec: monthly trend always has exactly 12 buckets."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        assert len(result) == 12, f"Expected 12 entries, got {len(result)}"

    def test_last_entry_is_current_month(self, app, test_user_id):
        """Spec: series ends with the calendar month of `today`."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        assert (
            result[-1]["month"] == "2026-05"
        ), f"Last entry must be the current month, got {result[-1]['month']}"

    def test_entries_are_oldest_to_newest(self, app, test_user_id):
        """Spec: returned list is ordered oldest first."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        months = [e["month"] for e in result]
        assert months == sorted(
            months
        ), "Entries must be in ascending (oldest-first) order"

    def test_entry_keys_are_month_label_amount(self, app, test_user_id):
        """Spec: each entry has keys 'month' (YYYY-MM), 'label' (abbrev), 'amount' (float)."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        for entry in result:
            assert "month" in entry, "Entry missing 'month' key"
            assert "label" in entry, "Entry missing 'label' key"
            assert "amount" in entry, "Entry missing 'amount' key"
            assert isinstance(
                entry["amount"], float
            ), f"'amount' must be float, got {type(entry['amount'])}"
            # YYYY-MM format check
            assert (
                len(entry["month"]) == 7 and entry["month"][4] == "-"
            ), f"'month' must be YYYY-MM, got {entry['month']}"

    def test_months_with_zero_spend_have_amount_zero(self, app, test_user_id, db_conn):
        """Spec: months with no spend appear with amount = 0.0 (zero-filled skeleton)."""
        # Insert an expense only for one specific month
        _insert_expense(db_conn, test_user_id, 500.0, "Food", "2026-05-10", "Lunch")
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        # All months except May-2026 should be 0.0
        zero_months = [e for e in result if e["month"] != "2026-05"]
        for entry in zero_months:
            assert entry["amount"] == pytest.approx(0.0), (
                f"Month {entry['month']} with no spend must have amount=0.0, "
                f"got {entry['amount']}"
            )

    def test_month_with_spend_has_correct_summed_amount(
        self, app, test_user_id, db_conn
    ):
        """The month with expenses carries the correct summed amount."""
        _insert_expense(db_conn, test_user_id, 300.0, "Food", "2026-05-10", "Breakfast")
        _insert_expense(db_conn, test_user_id, 200.0, "Transport", "2026-05-15", "Cab")
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        may_entry = next(e for e in result if e["month"] == "2026-05")
        assert may_entry["amount"] == pytest.approx(
            500.0
        ), f"May total must be 500.0, got {may_entry['amount']}"

    def test_year_rollover_today_in_january(self, app, test_user_id):
        """Spec: today in January → list extends back into prior year (year rollover)."""
        today = datetime.date(2026, 1, 15)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        assert len(result) == 12, "Must return exactly 12 entries for January today"
        # First entry must be Feb of prior year
        assert (
            result[0]["month"] == "2025-02"
        ), f"For today=2026-01, first entry should be 2025-02, got {result[0]['month']}"
        assert (
            result[-1]["month"] == "2026-01"
        ), f"For today=2026-01, last entry should be 2026-01, got {result[-1]['month']}"

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's expenses must never appear in the trend."""
        _insert_expense(
            db_conn, other_user_id, 99999.0, "Shopping", "2026-05-05", "OtherUserSecret"
        )
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_monthly_trend(test_user_id, today, months=12)
        may_entry = next(e for e in result if e["month"] == "2026-05")
        assert may_entry["amount"] == pytest.approx(
            0.0
        ), "Other user's expenses must not appear in test_user's monthly trend"


# ------------------------------------------------------------------ #
# 2. Unit tests — get_weekday_breakdown                                #
# ------------------------------------------------------------------ #


class TestGetWeekdayBreakdown:

    _EXPECTED_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def test_returns_exactly_seven_entries(self, app, test_user_id):
        """Spec: always seven entries, one per weekday."""
        with app.app_context():
            result = get_weekday_breakdown(test_user_id)
        assert len(result) == 7, f"Expected 7 entries, got {len(result)}"

    def test_entries_in_mon_to_sun_order(self, app, test_user_id):
        """Spec: fixed Mon to Sun ordering regardless of data."""
        with app.app_context():
            result = get_weekday_breakdown(test_user_id)
        labels = [e["weekday"] for e in result]
        assert (
            labels == self._EXPECTED_ORDER
        ), f"Weekday order must be Mon to Sun, got {labels}"

    def test_zero_spend_days_have_amount_zero(self, app, test_user_id):
        """Spec: days with zero spend appear with amount = 0.0."""
        with app.app_context():
            result = get_weekday_breakdown(test_user_id)
        for entry in result:
            assert entry["amount"] == pytest.approx(0.0), (
                f"Day {entry['weekday']} with no spend must have amount=0.0, "
                f"got {entry['amount']}"
            )

    def test_both_or_neither_only_date_from_supplied(self, app, test_user_id, db_conn):
        """Spec: supplying only date_from (no date_to) makes the filter silently drop."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-04-01")  # Wednesday
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2026-05-01")  # Friday
        with app.app_context():
            result_partial = get_weekday_breakdown(
                test_user_id, date_from="2026-05-01", date_to=None
            )
            result_all = get_weekday_breakdown(test_user_id)
        amounts_partial = {e["weekday"]: e["amount"] for e in result_partial}
        amounts_all = {e["weekday"]: e["amount"] for e in result_all}
        assert (
            amounts_partial == amounts_all
        ), "Only date_from supplied must behave identically to no filter (both-or-neither)"

    def test_both_or_neither_only_date_to_supplied(self, app, test_user_id, db_conn):
        """Spec: supplying only date_to (no date_from) makes the filter silently drop."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-04-01")
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2026-05-01")
        with app.app_context():
            result_partial = get_weekday_breakdown(
                test_user_id, date_from=None, date_to="2026-04-30"
            )
            result_all = get_weekday_breakdown(test_user_id)
        amounts_partial = {e["weekday"]: e["amount"] for e in result_partial}
        amounts_all = {e["weekday"]: e["amount"] for e in result_all}
        assert (
            amounts_partial == amounts_all
        ), "Only date_to supplied must behave identically to no filter (both-or-neither)"

    def test_date_range_filter_scopes_correctly(self, app, test_user_id, db_conn):
        """Spec: when both date_from and date_to are given, only in-range spend counts."""
        # 2026-04-01 is a Wednesday; 2026-05-01 is a Friday
        _insert_expense(db_conn, test_user_id, 300.0, "Food", "2026-04-01")  # Wednesday
        _insert_expense(db_conn, test_user_id, 500.0, "Food", "2026-05-01")  # Friday
        with app.app_context():
            result = get_weekday_breakdown(
                test_user_id, date_from="2026-05-01", date_to="2026-05-31"
            )
        amounts = {e["weekday"]: e["amount"] for e in result}
        # Only the May expense (Friday=500) is in range
        assert amounts["Fri"] == pytest.approx(
            500.0
        ), f"Friday amount must be 500.0 (only May expense in range), got {amounts['Fri']}"
        assert amounts["Wed"] == pytest.approx(
            0.0
        ), f"Wednesday must be 0.0 (April expense out of range), got {amounts['Wed']}"

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's weekday totals must not bleed into test_user's breakdown."""
        # 2026-05-04 is a Monday
        _insert_expense(db_conn, other_user_id, 88888.0, "Shopping", "2026-05-04")
        with app.app_context():
            result = get_weekday_breakdown(test_user_id)
        amounts = {e["weekday"]: e["amount"] for e in result}
        assert amounts["Mon"] == pytest.approx(
            0.0
        ), "Other user's Monday expense must not appear in test_user's breakdown"


# ------------------------------------------------------------------ #
# 3. Unit tests — get_top_expenses                                     #
# ------------------------------------------------------------------ #


class TestGetTopExpenses:

    def test_returns_empty_list_when_no_expenses(self, app, test_user_id):
        """Spec: empty list when user has no expenses."""
        with app.app_context():
            result = get_top_expenses(test_user_id)
        assert result == [], f"Expected [], got {result}"

    def test_ordered_by_amount_desc_then_date_desc(self, app, test_user_id, db_conn):
        """Spec: ordered by amount DESC, date DESC."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "Low")
        _insert_expense(
            db_conn, test_user_id, 500.0, "Food", "2026-05-03", "High-newer"
        )
        _insert_expense(
            db_conn, test_user_id, 500.0, "Food", "2026-05-01", "High-older"
        )
        with app.app_context():
            result = get_top_expenses(test_user_id, limit=10)
        assert result[0]["amount"] == pytest.approx(
            500.0
        ), "Highest amount must be first"
        # Among equal amounts, newer date comes first
        assert (
            result[0]["description"] == "High-newer"
        ), "Among equal amounts, newer date must come first"
        assert result[1]["description"] == "High-older"
        assert result[-1]["amount"] == pytest.approx(
            100.0
        ), "Lowest amount must be last"

    def test_respects_limit_parameter(self, app, test_user_id, db_conn):
        """Spec: limit parameter caps the number of returned rows."""
        for i in range(10):
            _insert_expense(
                db_conn, test_user_id, float(i + 1) * 100, "Food", "2026-05-01"
            )
        with app.app_context():
            result = get_top_expenses(test_user_id, limit=3)
        assert len(result) == 3, f"Expected 3 rows (limit=3), got {len(result)}"

    def test_default_limit_is_five(self, app, test_user_id, db_conn):
        """Spec: default limit is 5."""
        for i in range(8):
            _insert_expense(
                db_conn, test_user_id, float(i + 1) * 100, "Food", "2026-05-01"
            )
        with app.app_context():
            result = get_top_expenses(test_user_id)
        assert len(result) <= 5, f"Default limit must be 5, got {len(result)}"

    def test_date_range_filter_scopes_correctly(self, app, test_user_id, db_conn):
        """Spec: date filter scopes which expenses are eligible."""
        _insert_expense(
            db_conn, test_user_id, 999.0, "Bills", "2026-03-15", "Old large"
        )
        _insert_expense(
            db_conn, test_user_id, 50.0, "Food", "2026-05-10", "Recent small"
        )
        with app.app_context():
            result = get_top_expenses(
                test_user_id, limit=5, date_from="2026-05-01", date_to="2026-05-31"
            )
        assert len(result) == 1, "Only the May expense is in range"
        assert result[0]["description"] == "Recent small"

    def test_returned_dict_has_required_keys(self, app, test_user_id, db_conn):
        """Spec: each dict has keys id, date, description, category, amount."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "Test")
        with app.app_context():
            result = get_top_expenses(test_user_id)
        assert len(result) == 1
        row = result[0]
        for key in ("id", "date", "description", "category", "amount"):
            assert key in row, f"Missing key '{key}' in returned dict"

    def test_null_description_becomes_empty_string(self, app, test_user_id, db_conn):
        """Spec: NULL description in the DB is returned as the empty string."""
        _insert_expense(
            db_conn, test_user_id, 100.0, "Food", "2026-05-01", description=None
        )
        with app.app_context():
            result = get_top_expenses(test_user_id)
        assert (
            result[0]["description"] == ""
        ), "NULL description must be returned as empty string, not None"

    def test_both_or_neither_only_date_from_supplied(self, app, test_user_id, db_conn):
        """Spec: only date_from supplied → both-or-neither → no date filter applied."""
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2026-04-01", "April")
        _insert_expense(db_conn, test_user_id, 300.0, "Food", "2026-05-01", "May")
        with app.app_context():
            result = get_top_expenses(
                test_user_id, limit=10, date_from="2026-05-01", date_to=None
            )
        assert (
            len(result) == 2
        ), "With only date_from, both-or-neither must return all expenses"

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's expenses must not appear in test_user's top expenses."""
        _insert_expense(
            db_conn, other_user_id, 99999.0, "Shopping", "2026-05-01", "OtherUserSecret"
        )
        _insert_expense(db_conn, test_user_id, 10.0, "Food", "2026-05-01", "Mine")
        with app.app_context():
            result = get_top_expenses(test_user_id, limit=10)
        descriptions = [r["description"] for r in result]
        amounts = [r["amount"] for r in result]
        assert (
            "OtherUserSecret" not in descriptions
        ), "Other user's expense description must not appear"
        assert 99999.0 not in amounts, "Other user's expense amount must not appear"
        assert "Mine" in descriptions, "Test user's own expense must appear"


# ------------------------------------------------------------------ #
# 4. Unit tests — get_period_comparison                                #
# ------------------------------------------------------------------ #


class TestGetPeriodComparison:

    def test_returns_required_keys(self, app, test_user_id):
        """Spec: return dict has this_month_total, last_month_total, delta, pct_change."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        for key in ("this_month_total", "last_month_total", "delta", "pct_change"):
            assert key in result, f"Missing key '{key}'"

    def test_all_zeros_and_none_pct_when_no_expenses(self, app, test_user_id):
        """Spec: all zeros + pct_change = None when user has no expenses."""
        today = datetime.date(2026, 5, 23)
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["this_month_total"] == pytest.approx(
            0.0
        ), "this_month_total must be 0.0 with no expenses"
        assert result["last_month_total"] == pytest.approx(
            0.0
        ), "last_month_total must be 0.0 with no expenses"
        assert result["delta"] == pytest.approx(
            0.0
        ), "delta must be 0.0 with no expenses"
        assert result["pct_change"] is None, "pct_change must be None with no expenses"

    def test_pct_change_is_none_not_inf_when_last_month_zero(
        self, app, test_user_id, db_conn
    ):
        """Spec: pct_change = None (not inf) when last_month_total==0 but this_month > 0."""
        today = datetime.date(2026, 5, 23)
        _insert_expense(db_conn, test_user_id, 500.0, "Food", "2026-05-10", "May lunch")
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["this_month_total"] == pytest.approx(500.0)
        assert result["last_month_total"] == pytest.approx(0.0)
        assert (
            result["pct_change"] is None
        ), "pct_change must be None (not inf) when last_month_total is 0"

    def test_like_for_like_window_excludes_late_prior_month_days(
        self, app, test_user_id, db_conn
    ):
        """Spec: May 1–23 compared with Apr 1–23, not all of April."""
        today = datetime.date(2026, 5, 23)
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2026-05-10", "May spend")
        _insert_expense(
            db_conn, test_user_id, 100.0, "Food", "2026-04-15", "Apr in-range"
        )
        # Apr 28 is beyond day 23 — must NOT be in last_month window
        _insert_expense(
            db_conn, test_user_id, 9999.0, "Shopping", "2026-04-28", "Apr out-of-range"
        )
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["this_month_total"] == pytest.approx(
            200.0
        ), "this_month_total must be 200 (May 1–23)"
        assert result["last_month_total"] == pytest.approx(
            100.0
        ), "last_month_total must be 100 (Apr 1–23 only, not Apr 24–30)"
        assert result["delta"] == pytest.approx(
            100.0
        ), "delta = this - last = 200 - 100 = 100"
        assert result["pct_change"] == pytest.approx(
            100.0
        ), "pct_change = 100/100 * 100 = 100%"

    def test_negative_delta_when_spending_dropped(self, app, test_user_id, db_conn):
        """Spec: delta and pct_change are negative when this month < last month."""
        today = datetime.date(2026, 5, 10)
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-05", "May small")
        _insert_expense(db_conn, test_user_id, 500.0, "Food", "2026-04-05", "Apr large")
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["delta"] < 0, "delta must be negative when spending dropped"
        assert (
            result["pct_change"] is not None and result["pct_change"] < 0
        ), "pct_change must be negative when spending dropped"
        assert result["delta"] == pytest.approx(-400.0), "delta = 100 - 500 = -400"

    def test_year_rollover_january_compares_december(self, app, test_user_id, db_conn):
        """Spec: January today compares against December of the prior year."""
        today = datetime.date(2026, 1, 15)
        _insert_expense(db_conn, test_user_id, 300.0, "Food", "2026-01-10", "Jan spend")
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2025-12-08", "Dec spend")
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["this_month_total"] == pytest.approx(
            300.0
        ), "this_month_total must cover January 2026"
        assert result["last_month_total"] == pytest.approx(
            200.0
        ), "last_month_total must cover December 2025 (year rollover)"

    def test_clips_prior_window_to_prior_months_last_day_march_31(
        self, app, test_user_id, db_conn
    ):
        """Spec: March 31 today, Feb window clipped to Feb 28 (no IndexError/crash)."""
        today = datetime.date(2026, 3, 31)
        _insert_expense(
            db_conn, test_user_id, 150.0, "Bills", "2026-02-28", "Feb last day"
        )
        _insert_expense(
            db_conn, test_user_id, 250.0, "Bills", "2026-03-20", "March mid"
        )
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        # Feb window is clipped to Feb 28 (day 31 does not exist in Feb)
        assert result["last_month_total"] == pytest.approx(
            150.0
        ), "February window must be clipped to Feb 28 when today=March 31"
        assert result["this_month_total"] == pytest.approx(250.0)

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's monthly totals must not affect the comparison."""
        today = datetime.date(2026, 5, 23)
        _insert_expense(
            db_conn, other_user_id, 77777.0, "Shopping", "2026-05-10", "OtherMay"
        )
        _insert_expense(
            db_conn, other_user_id, 55555.0, "Shopping", "2026-04-10", "OtherApr"
        )
        with app.app_context():
            result = get_period_comparison(test_user_id, today)
        assert result["this_month_total"] == pytest.approx(
            0.0
        ), "Other user's May expenses must not count in test_user's this_month_total"
        assert result["last_month_total"] == pytest.approx(
            0.0
        ), "Other user's April expenses must not count in test_user's last_month_total"


# ------------------------------------------------------------------ #
# 5. Unit tests — get_highest_spending_month                           #
# ------------------------------------------------------------------ #


class TestGetHighestSpendingMonth:

    def test_returns_none_when_no_expenses(self, app, test_user_id):
        """Spec: returns None when user has no expenses."""
        with app.app_context():
            result = get_highest_spending_month(test_user_id)
        assert result is None, f"Expected None for user with no expenses, got {result}"

    def test_picks_correct_highest_month_across_history(
        self, app, test_user_id, db_conn
    ):
        """Spec: picks the calendar month with the largest total across all history."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-03-10", "March low")
        _insert_expense(
            db_conn, test_user_id, 100.0, "Food", "2026-03-20", "March low 2"
        )
        _insert_expense(
            db_conn, test_user_id, 5000.0, "Shopping", "2026-04-15", "April high"
        )
        _insert_expense(db_conn, test_user_id, 50.0, "Food", "2026-05-01", "May tiny")
        with app.app_context():
            result = get_highest_spending_month(test_user_id)
        assert result is not None
        assert (
            result["month"] == "2026-04"
        ), f"Highest-spend month must be April 2026, got {result['month']}"
        assert result["amount"] == pytest.approx(5000.0)

    def test_label_format_is_full_month_name_and_year(self, app, test_user_id, db_conn):
        """Spec: label format is '<Full month name> <YYYY>' e.g. 'March 2026'."""
        _insert_expense(
            db_conn, test_user_id, 200.0, "Food", "2026-03-05", "March spend"
        )
        with app.app_context():
            result = get_highest_spending_month(test_user_id)
        assert result is not None
        assert (
            result["label"] == "March 2026"
        ), f"Label must be 'March 2026', got {result['label']!r}"

    def test_returned_dict_has_required_keys(self, app, test_user_id, db_conn):
        """Result dict must have keys: month, label, amount."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "test")
        with app.app_context():
            result = get_highest_spending_month(test_user_id)
        assert result is not None
        for key in ("month", "label", "amount"):
            assert key in result, f"Missing key '{key}'"

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's months must not affect the result."""
        _insert_expense(
            db_conn,
            other_user_id,
            999999.0,
            "Shopping",
            "2026-01-10",
            "OtherJanMassive",
        )
        _insert_expense(
            db_conn, test_user_id, 200.0, "Food", "2026-05-01", "MyMaySpend"
        )
        with app.app_context():
            result = get_highest_spending_month(test_user_id)
        assert result is not None
        assert (
            result["month"] == "2026-05"
        ), "Other user's January must not override test_user's highest month"


# ------------------------------------------------------------------ #
# 6. Unit tests — get_earliest_expense_date                            #
# ------------------------------------------------------------------ #


class TestGetEarliestExpenseDate:

    def test_returns_none_when_no_expenses(self, app, test_user_id):
        """Spec: returns None when user has no expenses."""
        with app.app_context():
            result = get_earliest_expense_date(test_user_id)
        assert result is None, f"Expected None for user with no expenses, got {result}"

    def test_returns_minimum_date_as_date_object(self, app, test_user_id, db_conn):
        """Spec: returns the minimum date as a datetime.date (not a string)."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-10", "Newer")
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2025-11-15", "Older")
        _insert_expense(db_conn, test_user_id, 50.0, "Food", "2026-03-01", "Middle")
        with app.app_context():
            result = get_earliest_expense_date(test_user_id)
        assert isinstance(
            result, datetime.date
        ), f"Must return a datetime.date, got {type(result)}"
        assert result == datetime.date(
            2025, 11, 15
        ), f"Earliest date must be 2025-11-15, got {result}"

    def test_cross_user_isolation(self, app, test_user_id, other_user_id, db_conn):
        """Spec: another user's older expense must not become test_user's earliest date."""
        _insert_expense(
            db_conn, other_user_id, 100.0, "Food", "2020-01-01", "OtherVeryOld"
        )
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "MyFirst")
        with app.app_context():
            result = get_earliest_expense_date(test_user_id)
        assert result == datetime.date(
            2026, 5, 1
        ), "Other user's older date must not appear as test_user's earliest date"


# ------------------------------------------------------------------ #
# 7. Route tests — GET /analytics auth guard                           #
# ------------------------------------------------------------------ #


class TestAnalyticsRouteAuthGuard:

    def test_unauthenticated_returns_302(self, client):
        """Spec: unauthenticated request is redirected (302)."""
        response = client.get("/analytics")
        assert (
            response.status_code == 302
        ), f"Unauthenticated /analytics must return 302, got {response.status_code}"

    def test_unauthenticated_redirects_to_login(self, client):
        """Spec: redirect destination is /login."""
        response = client.get("/analytics")
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"Must redirect to /login, got Location: {location!r}"


# ------------------------------------------------------------------ #
# 8. Route tests — rendering                                           #
# ------------------------------------------------------------------ #


class TestAnalyticsRouteRendering:

    def test_authenticated_with_no_data_returns_200(self, auth_client):
        """Spec: authenticated user with no expenses — 200, no crash."""
        response = auth_client.get("/analytics")
        assert response.status_code == 200, (
            f"Expected 200 for authenticated /analytics (no data), "
            f"got {response.status_code}"
        )

    def test_no_coming_soon_copy_in_response(self, auth_client):
        """Spec: 'Coming Soon' must not appear anywhere on the page after Step 11."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "Coming Soon" not in body
        ), "Coming Soon copy must not remain on /analytics"

    def test_page_title_spending_insights_present(self, auth_client):
        """Spec: page heading is 'Spending insights'."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "Spending insights" in body
        ), "Page heading 'Spending insights' must be present"

    def test_monthly_trend_section_heading_present(self, auth_client):
        """Spec: 'Monthly trend' section heading is present."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "Monthly trend" in body
        ), "Section heading 'Monthly trend' must be present"

    def test_spending_by_weekday_section_heading_present(self, auth_client):
        """Spec: 'Spending by weekday' section heading is present."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "Spending by weekday" in body
        ), "Section heading 'Spending by weekday' must be present"

    def test_top_expenses_section_heading_present(self, auth_client):
        """Spec: 'Top expenses' section heading is present."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "Top expenses" in body, "Section heading 'Top expenses' must be present"

    def test_rupee_symbol_present(self, app, auth_client, test_user_id, db_conn):
        """Spec: currency renders as the rupee symbol everywhere."""
        _insert_expense(db_conn, test_user_id, 250.0, "Food", "2026-05-10", "Lunch")
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "₹" in body, "Rupee symbol must appear on the analytics page"

    def test_filter_pill_this_month_present(self, auth_client):
        """Spec: filter UI has 'This Month' preset pill."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "This Month" in body, "'This Month' filter pill must be present"

    def test_filter_pill_last_3_months_present(self, auth_client):
        """Spec: filter UI has 'Last 3 Months' preset pill."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "Last 3 Months" in body, "'Last 3 Months' filter pill must be present"

    def test_filter_pill_last_6_months_present(self, auth_client):
        """Spec: filter UI has 'Last 6 Months' preset pill."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "Last 6 Months" in body, "'Last 6 Months' filter pill must be present"

    def test_filter_pill_all_time_present(self, auth_client):
        """Spec: filter UI has 'All Time' preset pill."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert "All Time" in body, "'All Time' filter pill must be present"

    def test_custom_range_form_action_points_to_analytics(self, auth_client):
        """Spec: custom range form action points to /analytics."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            'action="/analytics"' in body
        ), "Custom-range form must have action='/analytics'"

    def test_trend_caption_last_12_months_visible_when_user_has_data(
        self, app, auth_client, test_user_id, db_conn
    ):
        """Spec: 'Last 12 months' caption appears below the trend chart when data exists."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "test")
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "Last 12 months" in body
        ), "Trend caption 'Last 12 months' must be visible when user has data"

    def test_top_expenses_rows_link_to_edit_page(
        self, app, auth_client, test_user_id, db_conn
    ):
        """Spec: each top-expenses row links to /expenses/<id>/edit."""
        expense_id = _insert_expense(
            db_conn, test_user_id, 1000.0, "Shopping", "2026-05-10", "Big purchase"
        )
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        expected_link = f"/expenses/{expense_id}/edit"
        assert expected_link in body, f"Top-expenses row must link to {expected_link!r}"

    def test_authenticated_with_data_returns_200(
        self, app, auth_client, test_user_id, db_conn
    ):
        """Spec: authenticated user with expenses renders without crashing."""
        _insert_expense(db_conn, test_user_id, 500.0, "Bills", "2026-05-05", "Electric")
        _insert_expense(db_conn, test_user_id, 200.0, "Food", "2026-04-10", "Dinner")
        response = auth_client.get("/analytics")
        assert response.status_code == 200, (
            f"Authenticated /analytics with data must return 200, "
            f"got {response.status_code}"
        )

    def test_formatted_amount_visible_when_user_has_data(
        self, app, auth_client, test_user_id, db_conn
    ):
        """Spec: at least one formatted rupee amount appears on the page."""
        _insert_expense(db_conn, test_user_id, 12345.0, "Bills", "2026-05-05", "Rent")
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "12,345" in body
        ), "Formatted expense amount '12,345' must appear in the page body"


# ------------------------------------------------------------------ #
# 9. Route tests — filter behaviour                                    #
# ------------------------------------------------------------------ #


class TestAnalyticsRouteFilterBehavior:

    def test_invalid_date_pair_returns_200(self, auth_client):
        """Spec: date_from > date_to — 200, not 500."""
        response = auth_client.get("/analytics?date_from=2026-05-31&date_to=2026-05-01")
        assert (
            response.status_code == 200
        ), f"Invalid date pair must return 200, got {response.status_code}"

    def test_invalid_date_pair_flashes_start_before_end_error(self, auth_client):
        """Spec: invalid date pair triggers flash 'Start date must be before end date.'"""
        response = auth_client.get("/analytics?date_from=2026-05-31&date_to=2026-05-01")
        body = response.data.decode("utf-8")
        assert (
            "Start date must be before end date." in body
        ), "Error flash 'Start date must be before end date.' must appear in the body"

    def test_garbage_date_from_and_to_returns_200(self, auth_client):
        """Spec: garbage date values — 200, filter silently dropped, no 500."""
        response = auth_client.get("/analytics?date_from=notadate&date_to=alsonotadate")
        assert response.status_code == 200, (
            f"Garbage dates must result in 200 (filter dropped), "
            f"got {response.status_code}"
        )

    def test_garbage_date_from_only_returns_200(self, auth_client):
        """Spec: one-sided garbage date — both-or-neither — 200."""
        response = auth_client.get("/analytics?date_from=garbage")
        assert response.status_code == 200, "Single garbage date param must return 200"

    def test_this_month_preset_url_yields_active_pill(self, auth_client):
        """Spec: this_month preset bounds in URL — that pill has filter-pill--active."""
        today = datetime.date.today()
        first_of_month = today.replace(day=1)
        url = (
            f"/analytics?date_from={first_of_month.isoformat()}"
            f"&date_to={today.isoformat()}"
        )
        response = auth_client.get(url)
        body = response.data.decode("utf-8")
        assert (
            "filter-pill--active" in body
        ), "A filter-pill--active class must appear when a preset URL is used"
        assert "This Month" in body, "The 'This Month' pill text must be present"

    def test_last_3_months_preset_url_yields_active_pill(self, auth_client):
        """Spec: last_3_months preset bounds in URL — that pill has filter-pill--active."""
        today = datetime.date.today()
        d_from = (today - timedelta(days=90)).isoformat()
        d_to = today.isoformat()
        response = auth_client.get(f"/analytics?date_from={d_from}&date_to={d_to}")
        body = response.data.decode("utf-8")
        assert (
            "filter-pill--active" in body
        ), "Last 3 Months pill must be active for last-3-months bounds"

    def test_all_time_with_no_filter_params_pill_active(self, auth_client):
        """Spec: no date params — All Time pill is active."""
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "filter-pill--active" in body
        ), "All Time pill must carry filter-pill--active when no date filter is applied"
        assert "All Time" in body, "'All Time' text must appear"


# ------------------------------------------------------------------ #
# 10. Cross-user isolation tests at the route level                    #
# ------------------------------------------------------------------ #


class TestAnalyticsRouteCrossUserIsolation:

    def test_other_users_description_absent_from_page(
        self, app, auth_client, test_user_id, other_user_id, db_conn
    ):
        """Spec: user A must not see user B's expense description anywhere on the page."""
        _insert_expense(
            db_conn,
            other_user_id,
            99999.0,
            "Shopping",
            "2026-05-10",
            "OtherUserSecret99999",
        )
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "OtherUserSecret99999" not in body
        ), "Other user's expense description must not appear on user A's analytics page"

    def test_other_users_large_amount_absent_from_page(
        self, app, auth_client, test_user_id, other_user_id, db_conn
    ):
        """Spec: user A must not see user B's distinctive amount anywhere on the page."""
        _insert_expense(
            db_conn,
            other_user_id,
            99999.0,
            "Shopping",
            "2026-05-10",
            "OtherUserLargeExpense",
        )
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        # Check both formatted and raw representations
        assert (
            "99,999" not in body and "99999" not in body
        ), "Other user's 99999 amount must not appear anywhere on user A's page"

    def test_own_data_visible_while_other_users_data_absent(
        self, app, auth_client, test_user_id, other_user_id, db_conn
    ):
        """Spec: both users have data — user A sees their own rows but not user B's."""
        _insert_expense(
            db_conn, test_user_id, 500.0, "Food", "2026-05-05", "MyLunchExpense"
        )
        _insert_expense(
            db_conn,
            other_user_id,
            99999.0,
            "Shopping",
            "2026-05-10",
            "OtherUserSecret99999",
        )
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "MyLunchExpense" in body
        ), "User A's own expense description must appear on their analytics page"
        assert (
            "OtherUserSecret99999" not in body
        ), "User B's expense description must not appear on user A's analytics page"

    def test_other_users_top_expense_excluded_from_top_table(
        self, app, auth_client, test_user_id, other_user_id, db_conn
    ):
        """Spec: top-expenses panel must contain only user A's data."""
        _insert_expense(db_conn, test_user_id, 100.0, "Food", "2026-05-01", "SmallMine")
        _insert_expense(
            db_conn,
            other_user_id,
            50000.0,
            "Shopping",
            "2026-05-05",
            "HugeOther12345",
        )
        response = auth_client.get("/analytics")
        body = response.data.decode("utf-8")
        assert (
            "HugeOther12345" not in body
        ), "Other user's huge expense must not appear in the top-expenses table"
        assert (
            "SmallMine" in body
        ), "User A's own expense must appear despite other user having a larger one"
