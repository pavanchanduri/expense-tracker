"""
tests/test_07-add-expense.py

Pytest test suite for Step 7: Add Expense.

All assertions are derived from the feature spec at
.claude/specs/07-add-expense.md — NOT from the implementation.

Fixture strategy
----------------
- `app`          : Flask app wired to an isolated temp-file SQLite DB
                   (monkeypatches database.db.DB_PATH) — real DB never touched.
- `client`       : Plain (unauthenticated) test client.
- `db_conn`      : Direct SQLite connection to the same temp-file DB so tests
                   can insert seed rows and verify DB side-effects without
                   going through the Flask layer.
- `test_user_id` : Inserts one test user; returns the new user id.
- `auth_client`  : Test client with `user_id` already placed in the session.
"""

import pytest
from datetime import date

from database.queries import CATEGORIES, insert_expense
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Core fixtures — `app`, `client`, `db_conn` live in conftest.py.     #
# ------------------------------------------------------------------ #


@pytest.fixture
def test_user_id(db_conn):
    """Insert a fresh test user and return its id."""
    cur = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (
            "Test User",
            "test@example.com",
            generate_password_hash("testpass", method="pbkdf2:sha256"),
        ),
    )
    db_conn.commit()
    return cur.lastrowid


@pytest.fixture
def auth_client(client, test_user_id):
    """Test client with the test user already placed in the session."""
    with client.session_transaction() as sess:
        sess["user_id"] = test_user_id
        sess["user_name"] = "Test User"
    return client


# ------------------------------------------------------------------ #
# Shared helpers                                                      #
# ------------------------------------------------------------------ #


def _expense_count(db_conn, user_id):
    """Return the number of expense rows belonging to user_id."""
    return db_conn.execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]


def _latest_expense(db_conn, user_id):
    """Return the most-recently-inserted expense row for user_id, or None."""
    return db_conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()


# A valid form payload used as the baseline for happy-path and variation tests.
_VALID_FORM = {
    "amount": "50.0",
    "category": "Food",
    "date": "2026-03-20",
    "description": "Lunch",
}

TODAY_ISO = date.today().isoformat()


# ------------------------------------------------------------------ #
# 1. Unit tests — insert_expense helper (database/queries.py)         #
# ------------------------------------------------------------------ #


class TestInsertExpenseHelper:
    """
    Direct unit tests for insert_expense(user_id, amount, category, date, description).
    These bypass the Flask layer entirely.
    """

    def test_insert_expense_returns_positive_integer_id(
        self, app, db_conn, test_user_id
    ):
        """Spec: insert_expense must return a positive integer row id."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        assert isinstance(
            row_id, int
        ), f"insert_expense must return an int, got {type(row_id)}"
        assert row_id > 0, "insert_expense must return a positive id"

    def test_insert_expense_row_queryable_after_insert(
        self, app, db_conn, test_user_id
    ):
        """Spec: After insert_expense, the row must exist in the expenses table."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert row is not None, "Expected the row to be queryable by its returned id"

    def test_insert_expense_stores_correct_user_id(self, app, db_conn, test_user_id):
        """Spec: Inserted row must store the supplied user_id."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT user_id FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert (
            row["user_id"] == test_user_id
        ), f"Expected user_id={test_user_id}, got {row['user_id']}"

    def test_insert_expense_stores_correct_amount(self, app, db_conn, test_user_id):
        """Spec: Inserted row must store the supplied amount."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert (
            pytest.approx(row["amount"]) == 50.0
        ), f"Expected amount 50.0, got {row['amount']}"

    def test_insert_expense_stores_correct_category(self, app, db_conn, test_user_id):
        """Spec: Inserted row must store the supplied category."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT category FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert (
            row["category"] == "Food"
        ), f"Expected category 'Food', got {row['category']}"

    def test_insert_expense_stores_correct_date(self, app, db_conn, test_user_id):
        """Spec: Inserted row must store the supplied date string as-is."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT date FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert (
            row["date"] == "2026-03-20"
        ), f"Expected date '2026-03-20', got {row['date']}"

    def test_insert_expense_stores_correct_description(
        self, app, db_conn, test_user_id
    ):
        """Spec: Inserted row must store the supplied description string."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 50.0, "Food", "2026-03-20", "Lunch")
        row = db_conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert (
            row["description"] == "Lunch"
        ), f"Expected description 'Lunch', got {row['description']}"

    def test_insert_expense_description_none_stores_sql_null(
        self, app, db_conn, test_user_id
    ):
        """Spec: description=None must be stored as SQL NULL (not the string 'None')."""
        with app.app_context():
            row_id = insert_expense(test_user_id, 75.0, "Transport", "2026-04-01", None)
        row = db_conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        assert row is not None, "Expected a row to be inserted when description=None"
        assert (
            row["description"] is None
        ), f"Expected SQL NULL for description=None, got {row['description']!r}"

    def test_insert_expense_none_description_still_inserts_row(
        self, app, db_conn, test_user_id
    ):
        """Spec: description=None is valid input — the row must be inserted successfully."""
        before = _expense_count(db_conn, test_user_id)
        with app.app_context():
            insert_expense(test_user_id, 75.0, "Transport", "2026-04-01", None)
        after = _expense_count(db_conn, test_user_id)
        assert (
            after == before + 1
        ), "Expected one new expense row when description=None is supplied"

    def test_insert_expense_sequential_calls_produce_unique_ids(
        self, app, db_conn, test_user_id
    ):
        """Spec: Two separate insert_expense calls must return different row ids."""
        with app.app_context():
            id1 = insert_expense(test_user_id, 100.0, "Bills", "2026-03-22", "Electric")
            id2 = insert_expense(
                test_user_id, 200.0, "Health", "2026-03-23", "Pharmacy"
            )
        assert id1 != id2, "Each insert_expense call must produce a unique row id"
        assert (
            _expense_count(db_conn, test_user_id) == 2
        ), "Expected exactly 2 rows after two insert_expense calls"


# ------------------------------------------------------------------ #
# 2. Auth guard — unauthenticated access                              #
# ------------------------------------------------------------------ #


class TestAddExpenseAuthGuard:

    def test_get_unauthenticated_returns_302(self, client):
        """Spec: Unauthenticated GET /expenses/add must return 302."""
        response = client.get("/expenses/add")
        assert (
            response.status_code == 302
        ), "Expected 302 for unauthenticated GET /expenses/add"

    def test_get_unauthenticated_redirects_to_login(self, client):
        """Spec: Unauthenticated GET /expenses/add must redirect to /login."""
        response = client.get("/expenses/add")
        assert "/login" in response.headers.get(
            "Location", ""
        ), "Expected redirect target to be /login for unauthenticated GET"

    def test_post_unauthenticated_returns_302(self, client):
        """Spec: Unauthenticated POST /expenses/add must return 302."""
        response = client.post("/expenses/add", data=_VALID_FORM)
        assert (
            response.status_code == 302
        ), "Expected 302 for unauthenticated POST /expenses/add"

    def test_post_unauthenticated_redirects_to_login(self, client):
        """Spec: Unauthenticated POST /expenses/add must redirect to /login."""
        response = client.post("/expenses/add", data=_VALID_FORM)
        assert "/login" in response.headers.get(
            "Location", ""
        ), "Expected redirect target to be /login for unauthenticated POST"

    def test_post_unauthenticated_inserts_no_row(self, client, db_conn):
        """Spec: Unauthenticated POST must not write any row to the expenses table."""
        client.post("/expenses/add", data=_VALID_FORM)
        count = db_conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
        assert count == 0, "Unauthenticated POST must not insert any expense row"


# ------------------------------------------------------------------ #
# 3. GET happy path — authenticated                                   #
# ------------------------------------------------------------------ #


class TestGetAddExpenseAuthenticated:

    def test_get_returns_200(self, auth_client):
        """Spec: Authenticated GET /expenses/add returns 200."""
        response = auth_client.get("/expenses/add")
        assert (
            response.status_code == 200
        ), "Expected 200 for authenticated GET /expenses/add"

    def test_get_renders_post_form(self, auth_client):
        """Spec: The page must contain a form element with method=POST."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8").lower()
        assert "<form" in body, "Expected a <form> element on the add-expense page"
        assert 'method="post"' in body, 'Expected the form to declare method="post"'

    def test_get_form_action_targets_add_expense_route(self, auth_client):
        """Spec: Form action must point to /expenses/add."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            "/expenses/add" in body
        ), "Expected form action /expenses/add on the add-expense page"

    def test_get_contains_amount_input(self, auth_client):
        """Spec: Form includes an amount input field."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            'name="amount"' in body
        ), 'Expected an input with name="amount" on the add-expense form'

    def test_get_contains_category_select(self, auth_client):
        """Spec: Form includes a category select."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            'name="category"' in body
        ), 'Expected a select with name="category" on the add-expense form'

    def test_get_contains_date_input(self, auth_client):
        """Spec: Form includes a date input."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            'name="date"' in body
        ), 'Expected an input with name="date" on the add-expense form'

    def test_get_contains_description_input(self, auth_client):
        """Spec: Form includes an optional description input."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            'name="description"' in body
        ), 'Expected an input with name="description" on the add-expense form'

    def test_get_date_defaults_to_today(self, auth_client):
        """Spec: The date field must be pre-filled with today's ISO date."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            TODAY_ISO in body
        ), f"Expected today's date {TODAY_ISO} as the default value in the date field"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_get_form_contains_each_category_option(self, auth_client, category):
        """Spec: The category <select> must contain all 7 fixed options."""
        response = auth_client.get("/expenses/add")
        body = response.data.decode("utf-8")
        assert (
            category in body
        ), f"Expected category option '{category}' to appear in the form"

    def test_get_categories_tuple_has_exactly_7_entries(self, auth_client):
        """Spec: Exactly 7 fixed categories: Food, Transport, Bills, Health,
        Entertainment, Shopping, Other."""
        assert (
            len(CATEGORIES) == 7
        ), f"CATEGORIES must contain exactly 7 entries, found {len(CATEGORIES)}: {CATEGORIES}"
        for expected in (
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ):
            assert expected in CATEGORIES, f"'{expected}' must be in CATEGORIES"


# ------------------------------------------------------------------ #
# 4. POST happy path — valid data                                     #
# ------------------------------------------------------------------ #


class TestPostAddExpenseHappyPath:

    def test_post_valid_redirects_to_profile(self, auth_client):
        """Spec: Valid POST must respond with 302 to /profile."""
        response = auth_client.post("/expenses/add", data=_VALID_FORM)
        assert (
            response.status_code == 302
        ), "Expected 302 redirect after valid POST to /expenses/add"
        assert "/profile" in response.headers.get(
            "Location", ""
        ), "Expected redirect target to be /profile"

    def test_post_valid_inserts_exactly_one_row(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Exactly one new expense row must be inserted in the DB."""
        before = _expense_count(db_conn, test_user_id)
        auth_client.post("/expenses/add", data=_VALID_FORM)
        after = _expense_count(db_conn, test_user_id)
        assert (
            after == before + 1
        ), "Expected exactly one new expense row after a valid POST"

    def test_post_valid_stores_correct_amount(self, auth_client, db_conn, test_user_id):
        """Spec: The inserted row must store the submitted amount."""
        auth_client.post("/expenses/add", data=_VALID_FORM)
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            pytest.approx(row["amount"]) == 50.0
        ), f"Expected stored amount 50.0, got {row['amount']}"

    def test_post_valid_stores_correct_category(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: The inserted row must store the submitted category."""
        auth_client.post("/expenses/add", data=_VALID_FORM)
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["category"] == "Food"
        ), f"Expected category 'Food', got {row['category']}"

    def test_post_valid_stores_correct_date(self, auth_client, db_conn, test_user_id):
        """Spec: The inserted row must store the submitted date."""
        auth_client.post("/expenses/add", data=_VALID_FORM)
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["date"] == "2026-03-20"
        ), f"Expected date '2026-03-20', got {row['date']}"

    def test_post_valid_stores_correct_description(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: The inserted row must store the submitted description."""
        auth_client.post("/expenses/add", data=_VALID_FORM)
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["description"] == "Lunch"
        ), f"Expected description 'Lunch', got {row['description']}"

    def test_post_valid_stores_correct_user_id(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Inserted row must be associated with the authenticated user."""
        auth_client.post("/expenses/add", data=_VALID_FORM)
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["user_id"] == test_user_id
        ), f"Expected user_id={test_user_id} on inserted row, got {row['user_id']}"


# ------------------------------------------------------------------ #
# 5. POST — optional description (blank / whitespace)                 #
# ------------------------------------------------------------------ #


class TestPostAddExpenseBlankDescription:

    def test_post_blank_description_redirects_to_profile(self, auth_client):
        """Spec: A blank description is valid — route must redirect to /profile."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "description": ""}
        )
        assert (
            response.status_code == 302
        ), "Expected 302 redirect when description is blank"
        assert "/profile" in response.headers.get(
            "Location", ""
        ), "Expected redirect to /profile when description is blank"

    def test_post_blank_description_inserts_row(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Blank description is not a validation error — row must be inserted."""
        before = _expense_count(db_conn, test_user_id)
        auth_client.post("/expenses/add", data={**_VALID_FORM, "description": ""})
        after = _expense_count(db_conn, test_user_id)
        assert (
            after == before + 1
        ), "Expected one new row even when description is blank"

    def test_post_blank_description_stores_null(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: A blank description must be stored as SQL NULL (not empty string)."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "description": ""})
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["description"] is None
        ), f"Expected NULL description for blank input, got {row['description']!r}"

    def test_post_whitespace_only_description_stores_null(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: A whitespace-only description is stripped to empty → stored as NULL."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "description": "   "})
        row = _latest_expense(db_conn, test_user_id)
        assert row is not None
        assert (
            row["description"] is None
        ), f"Expected NULL for whitespace-only description, got {row['description']!r}"


# ------------------------------------------------------------------ #
# 6. POST validation errors — amount                                  #
# ------------------------------------------------------------------ #


class TestPostAddExpenseAmountValidation:

    def _assert_form_rerendered(self, response, label):
        assert (
            response.status_code == 200
        ), f"Expected 200 (form re-render) for invalid amount: {label}"

    def _assert_no_row(self, db_conn, user_id, label):
        count = _expense_count(db_conn, user_id)
        assert count == 0, f"Expected no row inserted for invalid amount: {label}"

    # --- missing / empty ---

    def test_post_missing_amount_rerenders_form(self, auth_client):
        """Spec: Empty amount field → form re-rendered (200)."""
        response = auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": ""})
        self._assert_form_rerendered(response, "empty string")

    def test_post_missing_amount_shows_error_message(self, auth_client):
        """Spec: Empty amount field → error message in response."""
        response = auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": ""})
        body = response.data.decode("utf-8")
        assert (
            "Amount must be a number greater than 0." in body
        ), "Expected error message 'Amount must be a number greater than 0.' for empty amount"

    def test_post_missing_amount_no_row_inserted(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Empty amount → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": ""})
        self._assert_no_row(db_conn, test_user_id, "empty string")

    # --- zero ---

    def test_post_zero_amount_rerenders_form(self, auth_client):
        """Spec: amount=0 → form re-rendered (200)."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": "0"}
        )
        self._assert_form_rerendered(response, "zero")

    def test_post_zero_amount_shows_error_message(self, auth_client):
        """Spec: amount=0 → error message in response."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": "0"}
        )
        body = response.data.decode("utf-8")
        assert (
            "Amount must be a number greater than 0." in body
        ), "Expected error message for amount=0"

    def test_post_zero_amount_no_row_inserted(self, auth_client, db_conn, test_user_id):
        """Spec: amount=0 → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": "0"})
        self._assert_no_row(db_conn, test_user_id, "zero")

    # --- negative ---

    def test_post_negative_amount_rerenders_form(self, auth_client):
        """Spec: Negative amount → form re-rendered (200)."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": "-10"}
        )
        self._assert_form_rerendered(response, "negative")

    def test_post_negative_amount_shows_error_message(self, auth_client):
        """Spec: Negative amount → error message in response."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": "-10"}
        )
        body = response.data.decode("utf-8")
        assert (
            "Amount must be a number greater than 0." in body
        ), "Expected error message for negative amount"

    def test_post_negative_amount_no_row_inserted(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Negative amount → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": "-10"})
        self._assert_no_row(db_conn, test_user_id, "negative")

    # --- non-numeric (parametrized) ---

    @pytest.mark.parametrize(
        "bad_amount",
        [
            "abc",
            "one hundred",
            "50px",
            "1e3x",
            "50,00",
            "$50",
            "₹50",
            " ",
        ],
    )
    def test_post_non_numeric_amount_rerenders_form(self, auth_client, bad_amount):
        """Spec: Non-numeric amount → form re-rendered (200)."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": bad_amount}
        )
        assert (
            response.status_code == 200
        ), f"Expected 200 (form re-render) for non-numeric amount {bad_amount!r}"

    @pytest.mark.parametrize(
        "bad_amount",
        [
            "abc",
            "one hundred",
            "50px",
            "1e3x",
            "50,00",
            "$50",
            "₹50",
            " ",
        ],
    )
    def test_post_non_numeric_amount_shows_error_message(self, auth_client, bad_amount):
        """Spec: Non-numeric amount → error message present in response."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "amount": bad_amount}
        )
        body = response.data.decode("utf-8")
        assert (
            "Amount must be a number greater than 0." in body
        ), f"Expected error message for non-numeric amount {bad_amount!r}"

    @pytest.mark.parametrize(
        "bad_amount",
        [
            "abc",
            "one hundred",
            "50px",
            "1e3x",
            "50,00",
            "$50",
        ],
    )
    def test_post_non_numeric_amount_no_row_inserted(
        self, auth_client, db_conn, test_user_id, bad_amount
    ):
        """Spec: Non-numeric amount → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "amount": bad_amount})
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), f"Expected no row for non-numeric amount {bad_amount!r}"


# ------------------------------------------------------------------ #
# 7. POST validation errors — category                                #
# ------------------------------------------------------------------ #


class TestPostAddExpenseCategoryValidation:

    def test_post_invalid_category_rerenders_form(self, auth_client):
        """Spec: Category not in the fixed list → form re-rendered (200)."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "category": "Bogus"}
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) for an invalid category"

    def test_post_invalid_category_shows_error_message(self, auth_client):
        """Spec: Invalid category → error message in response."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "category": "Bogus"}
        )
        body = response.data.decode("utf-8")
        assert (
            "Please choose a valid category." in body
        ), "Expected error 'Please choose a valid category.' for an invalid category"

    def test_post_invalid_category_no_row_inserted(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Invalid category → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "category": "Bogus"})
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), "Expected no row for an invalid category"

    def test_post_empty_category_rerenders_form(self, auth_client):
        """Spec: Empty string category is not in the fixed list → form re-rendered."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "category": ""}
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) for an empty category"

    def test_post_empty_category_no_row_inserted(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: Empty category → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "category": ""})
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), "Expected no row for an empty category"

    def test_post_sql_injection_in_category_rejected(
        self, auth_client, db_conn, test_user_id
    ):
        """Spec: A category value that is not in CATEGORIES must always be rejected,
        even if it looks like SQL (parameterised queries prevent injection)."""
        auth_client.post(
            "/expenses/add",
            data={**_VALID_FORM, "category": "Food'; DROP TABLE expenses;--"},
        )
        # Must not insert any row
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), "Expected no row when category contains SQL injection attempt"
        # The expenses table must still exist (injection had no effect)
        count = db_conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
        assert isinstance(
            count, int
        ), "expenses table must still be intact after SQL injection attempt"


# ------------------------------------------------------------------ #
# 8. POST validation errors — date                                    #
# ------------------------------------------------------------------ #


class TestPostAddExpenseDateValidation:

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "2026/03/20",  # wrong separator
            "20-03-2026",  # reversed order
            "2026-13-01",  # month 13
            "2026-00-15",  # month 0
            "2026-02-30",  # Feb 30 does not exist
            "9999-99-99",  # completely out of range
        ],
    )
    def test_post_malformed_date_rerenders_form(self, auth_client, bad_date):
        """Spec: Malformed date string → form re-rendered (200)."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "date": bad_date}
        )
        assert (
            response.status_code == 200
        ), f"Expected 200 (form re-render) for malformed date {bad_date!r}"

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "2026/03/20",
            "20-03-2026",
            "2026-13-01",
            "2026-00-15",
            "2026-02-30",
        ],
    )
    def test_post_malformed_date_shows_error_message(self, auth_client, bad_date):
        """Spec: Malformed date → error message in response."""
        response = auth_client.post(
            "/expenses/add", data={**_VALID_FORM, "date": bad_date}
        )
        body = response.data.decode("utf-8")
        assert (
            "Please enter a valid date" in body
        ), f"Expected 'Please enter a valid date' error for malformed date {bad_date!r}"

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "2026/03/20",
            "20-03-2026",
            "2026-13-01",
            "2026-00-15",
        ],
    )
    def test_post_malformed_date_no_row_inserted(
        self, auth_client, db_conn, test_user_id, bad_date
    ):
        """Spec: Malformed date → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "date": bad_date})
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), f"Expected no row for malformed date {bad_date!r}"

    def test_post_empty_date_rerenders_form(self, auth_client):
        """Spec: Empty date → form re-rendered (200)."""
        response = auth_client.post("/expenses/add", data={**_VALID_FORM, "date": ""})
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) for an empty date"

    def test_post_empty_date_shows_error_message(self, auth_client):
        """Spec: Empty date → error message in response."""
        response = auth_client.post("/expenses/add", data={**_VALID_FORM, "date": ""})
        body = response.data.decode("utf-8")
        assert (
            "Please enter a valid date" in body
        ), "Expected 'Please enter a valid date' error for empty date"

    def test_post_empty_date_no_row_inserted(self, auth_client, db_conn, test_user_id):
        """Spec: Empty date → no row inserted."""
        auth_client.post("/expenses/add", data={**_VALID_FORM, "date": ""})
        assert (
            _expense_count(db_conn, test_user_id) == 0
        ), "Expected no row for empty date"


# ------------------------------------------------------------------ #
# 9. POST error — form repopulates submitted values                   #
# ------------------------------------------------------------------ #


class TestPostAddExpenseFormRepopulation:
    """
    Spec: On any validation error the form must be re-rendered with the
    previously submitted values pre-filled so the user does not lose input.
    """

    def test_error_repopulates_category_value(self, auth_client):
        """Previously submitted category must appear in the re-rendered form."""
        data = {**_VALID_FORM, "amount": "-5", "category": "Transport"}
        response = auth_client.post("/expenses/add", data=data)
        body = response.data.decode("utf-8")
        assert (
            "Transport" in body
        ), "Expected category 'Transport' to be repopulated in the error form"

    def test_error_repopulates_date_value(self, auth_client):
        """Previously submitted date must appear in the re-rendered form."""
        data = {**_VALID_FORM, "amount": "-5", "date": "2026-05-15"}
        response = auth_client.post("/expenses/add", data=data)
        body = response.data.decode("utf-8")
        assert (
            "2026-05-15" in body
        ), "Expected date '2026-05-15' to be repopulated in the error form"

    def test_error_repopulates_description_value(self, auth_client):
        """Previously submitted description must appear in the re-rendered form."""
        data = {**_VALID_FORM, "amount": "-5", "description": "My lunch note"}
        response = auth_client.post("/expenses/add", data=data)
        body = response.data.decode("utf-8")
        assert (
            "My lunch note" in body
        ), "Expected description 'My lunch note' to be repopulated in the error form"


# ------------------------------------------------------------------ #
# 10. Profile page — Add Expense navigation link                      #
# ------------------------------------------------------------------ #


class TestProfilePageAddExpenseLink:

    def test_profile_page_contains_add_expense_link(self, auth_client):
        """Spec: The authenticated profile page must expose a link to /expenses/add
        so users can navigate to the add-expense form (Add Expense button)."""
        response = auth_client.get("/profile")
        assert (
            response.status_code == 200
        ), "Expected 200 for authenticated GET /profile"
        body = response.data.decode("utf-8")
        assert (
            "/expenses/add" in body
        ), "Expected an /expenses/add link or button on the profile page"
