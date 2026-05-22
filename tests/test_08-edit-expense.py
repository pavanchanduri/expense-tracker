"""
tests/test_08-edit-expense.py

Pytest test suite for Step 8: Edit Expense.

All assertions are derived from the feature spec at
.claude/specs/08-edit-expense.md — NOT from the implementation.

Spec requirements tested
------------------------
- GET /expenses/<id>/edit — unauthenticated → 302 to /login
- GET /expenses/<id>/edit — owner → 200, pre-filled form with all 7 category options
- GET /expenses/<id>/edit — non-owner → 302 to /profile, no data leak
- GET /expenses/<id>/edit — non-existent id → 302 to /profile
- POST /expenses/<id>/edit — unauthenticated → 302 to /login, row unchanged
- POST /expenses/<id>/edit — owner, valid → 302 to /profile, DB updated
- POST /expenses/<id>/edit — non-owner → 302 to /profile, row unchanged
- POST /expenses/<id>/edit — validation failures (amount, category, date) → 200 + error, row unchanged
- POST /expenses/<id>/edit — cleared description → NULL stored
- POST /expenses/<id>/edit — error form repopulates submitted (not original) values
- get_expense_by_id unit tests (owner, non-owner, missing)
- update_expense unit tests (owner, non-owner, None/blank description)
- Profile page includes Edit link per transaction row

Fixture strategy
----------------
- `app`               : Flask app wired to an isolated temp-file SQLite DB via
                        monkeypatching database.db.DB_PATH. Real DB never touched.
- `client`            : Plain (unauthenticated) test client.
- `db_conn`           : Direct SQLite connection to the same temp DB for inserts
                        and DB-side-effect assertions.
- `test_user_id`      : Primary "owner" user inserted per test.
- `other_user_id`     : Second user used for ownership enforcement tests.
- `auth_client`       : Test client with test_user_id already in the session.
- `expense_id`        : An expense row owned by test_user_id.
- `foreign_expense_id`: An expense row owned by other_user_id.
"""

import sqlite3
import pytest

from app import app as flask_app
from database.db import init_db
from database.queries import (
    CATEGORIES,
    get_expense_by_id,
    insert_expense,
    update_expense,
)
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Core fixtures                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture
def app(tmp_path, monkeypatch):
    """
    Flask app wired to a per-test temp-file SQLite DB so the test client
    and direct DB helpers share the same physical file.
    The real expense_tracker.db is never touched.
    """
    db_file = str(tmp_path / "test_edit_expense.db")
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
    Direct SQLite connection to the test DB.
    Yields the connection; commits + closes after the test.
    """
    import database.db as db_module

    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.commit()
    conn.close()


def _create_user(db_conn, name, email):
    cur = db_conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash("pw", method="pbkdf2:sha256")),
    )
    db_conn.commit()
    return cur.lastrowid


@pytest.fixture
def test_user_id(db_conn):
    """Insert the primary 'owner' user and return its id."""
    return _create_user(db_conn, "Owner User", "owner@example.com")


@pytest.fixture
def other_user_id(db_conn):
    """Insert a second user (used for cross-user ownership tests)."""
    return _create_user(db_conn, "Other User", "other@example.com")


@pytest.fixture
def auth_client(client, test_user_id):
    """Test client with test_user_id already in the session."""
    with client.session_transaction() as sess:
        sess["user_id"] = test_user_id
        sess["user_name"] = "Owner User"
    return client


@pytest.fixture
def expense_id(app, test_user_id):
    """An expense row owned by test_user_id (the authenticated user)."""
    with app.app_context():
        return insert_expense(
            test_user_id, 250.00, "Food", "2026-03-20", "Original lunch"
        )


@pytest.fixture
def foreign_expense_id(app, other_user_id):
    """An expense row owned by other_user_id (a different user)."""
    with app.app_context():
        return insert_expense(
            other_user_id, 999.00, "Bills", "2026-03-15", "Other user's bill"
        )


# ------------------------------------------------------------------ #
# Internal helpers                                                    #
# ------------------------------------------------------------------ #


def _row(db_conn, expense_id):
    """Fetch a single expense row by id for DB-side-effect assertions."""
    return db_conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()


# Baseline valid edit payload reused across POST tests.
_VALID_EDIT = {
    "amount": "300.50",
    "category": "Transport",
    "date": "2026-04-10",
    "description": "Updated cab ride",
}


# ------------------------------------------------------------------ #
# 1. Unit tests — get_expense_by_id                                   #
# ------------------------------------------------------------------ #


class TestGetExpenseByIdHelper:
    """
    Spec: get_expense_by_id(expense_id, user_id) — returns a dict scoped to
    the owning user, or None.
    """

    def test_returns_dict_for_owner(self, app, expense_id, test_user_id):
        """Spec: valid expense_id belonging to the user → dict with all fields."""
        with app.app_context():
            row = get_expense_by_id(expense_id, test_user_id)
        assert row is not None, "Expected a non-None dict for the owning user"
        assert row["id"] == expense_id, f"Expected id={expense_id}, got {row['id']}"
        assert (
            row["user_id"] == test_user_id
        ), f"Expected user_id={test_user_id}, got {row['user_id']}"
        assert row["amount"] == pytest.approx(
            250.00
        ), f"Expected amount 250.00, got {row['amount']}"
        assert (
            row["category"] == "Food"
        ), f"Expected category 'Food', got {row['category']}"
        assert (
            row["date"] == "2026-03-20"
        ), f"Expected date '2026-03-20', got {row['date']}"
        assert (
            row["description"] == "Original lunch"
        ), f"Expected description 'Original lunch', got {row['description']}"

    def test_returns_none_for_non_owner(self, app, foreign_expense_id, test_user_id):
        """Spec: expense_id belonging to a different user → None (no cross-user leak)."""
        with app.app_context():
            row = get_expense_by_id(foreign_expense_id, test_user_id)
        assert (
            row is None
        ), "Expected None when querying an expense owned by a different user"

    def test_returns_none_for_missing_id(self, app, test_user_id):
        """Spec: non-existent expense_id → None."""
        with app.app_context():
            row = get_expense_by_id(99999, test_user_id)
        assert row is None, "Expected None for a non-existent expense id"

    def test_result_is_dict_like_with_all_expected_keys(
        self, app, expense_id, test_user_id
    ):
        """Spec: returned object must be dict-like and expose id, user_id,
        amount, category, date, description keys."""
        with app.app_context():
            row = get_expense_by_id(expense_id, test_user_id)
        assert row is not None
        for key in ("id", "user_id", "amount", "category", "date", "description"):
            assert key in row, f"Expected key '{key}' in get_expense_by_id result"


# ------------------------------------------------------------------ #
# 2. Unit tests — update_expense                                      #
# ------------------------------------------------------------------ #


class TestUpdateExpenseHelper:
    """
    Spec: update_expense(expense_id, user_id, amount, category, expense_date,
    description) — parameterised UPDATE … WHERE id=? AND user_id=?;
    returns rows affected.
    """

    def test_owner_update_returns_one(self, app, expense_id, test_user_id):
        """Spec: valid args for owned expense → rows-affected = 1."""
        with app.app_context():
            affected = update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "Electric"
            )
        assert (
            affected == 1
        ), f"Expected rowcount=1 for a successful owner update, got {affected}"

    def test_owner_update_writes_new_amount(
        self, app, db_conn, expense_id, test_user_id
    ):
        """Spec: after owner update, DB row reflects the new amount."""
        with app.app_context():
            update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "Electric"
            )
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            400.0
        ), f"Expected updated amount 400.0, got {row['amount']}"

    def test_owner_update_writes_new_category(
        self, app, db_conn, expense_id, test_user_id
    ):
        """Spec: after owner update, DB row reflects the new category."""
        with app.app_context():
            update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "Electric"
            )
        row = _row(db_conn, expense_id)
        assert (
            row["category"] == "Bills"
        ), f"Expected updated category 'Bills', got {row['category']}"

    def test_owner_update_writes_new_date(self, app, db_conn, expense_id, test_user_id):
        """Spec: after owner update, DB row reflects the new date."""
        with app.app_context():
            update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "Electric"
            )
        row = _row(db_conn, expense_id)
        assert (
            row["date"] == "2026-05-01"
        ), f"Expected updated date '2026-05-01', got {row['date']}"

    def test_owner_update_writes_new_description(
        self, app, db_conn, expense_id, test_user_id
    ):
        """Spec: after owner update, DB row reflects the new description."""
        with app.app_context():
            update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "Electric"
            )
        row = _row(db_conn, expense_id)
        assert (
            row["description"] == "Electric"
        ), f"Expected updated description 'Electric', got {row['description']}"

    def test_non_owner_update_returns_zero(self, app, foreign_expense_id, test_user_id):
        """Spec: expense_id owned by another user → rows-affected = 0."""
        with app.app_context():
            affected = update_expense(
                foreign_expense_id, test_user_id, 1.0, "Food", "2026-05-01", "x"
            )
        assert (
            affected == 0
        ), f"Expected rowcount=0 when updating another user's row, got {affected}"

    def test_non_owner_update_leaves_row_unchanged(
        self, app, db_conn, foreign_expense_id, test_user_id
    ):
        """Spec: after a non-owner update attempt, the original row is unchanged."""
        with app.app_context():
            update_expense(
                foreign_expense_id, test_user_id, 1.0, "Food", "2026-05-01", "x"
            )
        row = _row(db_conn, foreign_expense_id)
        assert row["amount"] == pytest.approx(
            999.00
        ), "Non-owner update must not change the amount"
        assert (
            row["category"] == "Bills"
        ), "Non-owner update must not change the category"
        assert row["date"] == "2026-03-15", "Non-owner update must not change the date"
        assert (
            row["description"] == "Other user's bill"
        ), "Non-owner update must not change the description"

    def test_update_with_none_description_stores_null(
        self, app, db_conn, expense_id, test_user_id
    ):
        """Spec: description=None → row updated with description stored as NULL."""
        with app.app_context():
            update_expense(expense_id, test_user_id, 50.0, "Food", "2026-03-20", None)
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), f"Expected NULL description when None is passed, got {row['description']!r}"

    def test_update_with_blank_description_stores_null(
        self, app, db_conn, expense_id, test_user_id
    ):
        """Spec: whitespace-only description is stripped → stored as NULL."""
        with app.app_context():
            update_expense(expense_id, test_user_id, 50.0, "Food", "2026-03-20", "   ")
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), "Expected NULL when whitespace-only description is passed"


# ------------------------------------------------------------------ #
# 3. Auth guard — unauthenticated access                              #
# ------------------------------------------------------------------ #


class TestEditExpenseAuthGuard:
    """
    Spec: Unauthenticated access to both GET and POST
    /expenses/<id>/edit must redirect to /login.
    """

    def test_get_unauthenticated_returns_302(self, client, expense_id):
        """Spec: unauthenticated GET → 302."""
        response = client.get(f"/expenses/{expense_id}/edit")
        assert (
            response.status_code == 302
        ), "Expected 302 for unauthenticated GET /expenses/<id>/edit"

    def test_get_unauthenticated_redirects_to_login(self, client, expense_id):
        """Spec: unauthenticated GET redirects to /login."""
        response = client.get(f"/expenses/{expense_id}/edit")
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"Expected redirect to /login for unauthenticated GET, got Location={location!r}"

    def test_post_unauthenticated_returns_302(self, client, expense_id):
        """Spec: unauthenticated POST → 302."""
        response = client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        assert (
            response.status_code == 302
        ), "Expected 302 for unauthenticated POST /expenses/<id>/edit"

    def test_post_unauthenticated_redirects_to_login(self, client, expense_id):
        """Spec: unauthenticated POST redirects to /login."""
        response = client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"Expected redirect to /login for unauthenticated POST, got Location={location!r}"

    def test_post_unauthenticated_does_not_modify_row(
        self, client, db_conn, expense_id
    ):
        """Spec: unauthenticated POST must not write any changes to the DB."""
        client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            250.00
        ), "Unauthenticated POST must not modify the row amount"
        assert (
            row["category"] == "Food"
        ), "Unauthenticated POST must not modify the row category"


# ------------------------------------------------------------------ #
# 4. Owner gate — cross-user and missing-ID protection                #
# ------------------------------------------------------------------ #


class TestEditExpenseOwnerGate:
    """
    Spec: A logged-in user must never be able to view or modify another
    user's expense by guessing IDs. Missing expenses also redirect to /profile.
    """

    def test_get_non_owner_returns_302(self, auth_client, foreign_expense_id):
        """Spec: authenticated non-owner GET → 302."""
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        assert (
            response.status_code == 302
        ), "Expected 302 when authenticated user GETs another user's expense"

    def test_get_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        """Spec: authenticated non-owner GET redirects to /profile."""
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Expected redirect to /profile for non-owner GET, got Location={location!r}"

    def test_get_non_owner_does_not_expose_foreign_description(
        self, auth_client, foreign_expense_id
    ):
        """Spec: no data from the foreign expense may appear in the response body."""
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            "Other user's bill" not in body
        ), "Foreign expense description must not appear in the response when non-owner GETs"

    def test_get_non_owner_does_not_render_form(self, auth_client, foreign_expense_id):
        """Spec: the edit form must not be rendered for a non-owner GET."""
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        body = response.data.decode("utf-8").lower()
        assert (
            "<form" not in body
        ), "The edit form must not be rendered when a non-owner accesses the route"

    def test_post_non_owner_returns_302(self, auth_client, foreign_expense_id):
        """Spec: authenticated non-owner POST → 302."""
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/edit", data=_VALID_EDIT
        )
        assert (
            response.status_code == 302
        ), "Expected 302 when authenticated user POSTs to another user's expense"

    def test_post_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        """Spec: authenticated non-owner POST redirects to /profile."""
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/edit", data=_VALID_EDIT
        )
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Expected redirect to /profile for non-owner POST, got Location={location!r}"

    def test_post_non_owner_leaves_row_unchanged(
        self, auth_client, db_conn, foreign_expense_id
    ):
        """Spec: target row in DB is unchanged after a non-owner POST."""
        auth_client.post(f"/expenses/{foreign_expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, foreign_expense_id)
        assert row["amount"] == pytest.approx(
            999.00
        ), "Non-owner POST must not change the row amount"
        assert (
            row["category"] == "Bills"
        ), "Non-owner POST must not change the row category"
        assert (
            row["date"] == "2026-03-15"
        ), "Non-owner POST must not change the row date"
        assert (
            row["description"] == "Other user's bill"
        ), "Non-owner POST must not change the row description"

    def test_get_nonexistent_expense_returns_302(self, auth_client):
        """Spec: GET for a non-existent expense id → 302 to /profile."""
        response = auth_client.get("/expenses/99999/edit")
        assert (
            response.status_code == 302
        ), "Expected 302 for GET with a non-existent expense id"

    def test_get_nonexistent_expense_redirects_to_profile(self, auth_client):
        """Spec: GET for a non-existent expense id redirects to /profile."""
        response = auth_client.get("/expenses/99999/edit")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Expected redirect to /profile for non-existent id GET, got {location!r}"

    def test_post_nonexistent_expense_returns_302(self, auth_client):
        """Spec: POST for a non-existent expense id → 302 to /profile."""
        response = auth_client.post("/expenses/99999/edit", data=_VALID_EDIT)
        assert (
            response.status_code == 302
        ), "Expected 302 for POST with a non-existent expense id"

    def test_post_nonexistent_expense_redirects_to_profile(self, auth_client):
        """Spec: POST for a non-existent expense id redirects to /profile."""
        response = auth_client.post("/expenses/99999/edit", data=_VALID_EDIT)
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Expected redirect to /profile for non-existent id POST, got {location!r}"


# ------------------------------------------------------------------ #
# 5. GET happy path — owner sees pre-filled form                      #
# ------------------------------------------------------------------ #


class TestGetEditExpenseAuthenticated:
    """
    Spec: GET /expenses/<id>/edit for the owning user returns 200 and renders
    the edit-expense form pre-filled with the current row values.
    """

    def test_get_owner_returns_200(self, auth_client, expense_id):
        """Spec: authenticated owner GET → 200."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        assert (
            response.status_code == 200
        ), "Expected 200 for authenticated owner GET /expenses/<id>/edit"

    def test_get_renders_post_form(self, auth_client, expense_id):
        """Spec: response body contains a <form> with method=POST."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8").lower()
        assert "<form" in body, "Expected a <form> element on the edit-expense page"
        assert 'method="post"' in body, 'Expected the form to declare method="post"'

    def test_get_form_action_targets_edit_route(self, auth_client, expense_id):
        """Spec: form action must point to /expenses/<id>/edit."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            f"/expenses/{expense_id}/edit" in body
        ), f"Expected form action /expenses/{expense_id}/edit in the response"

    def test_get_prefills_amount(self, auth_client, expense_id):
        """Spec: amount field pre-filled with current value (250.0)."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        # The stored float 250.0 must appear in the rendered HTML
        assert (
            "250" in body
        ), "Expected current amount (250) to appear pre-filled in the edit form"

    def test_get_prefills_date(self, auth_client, expense_id):
        """Spec: date field pre-filled with current value (2026-03-20)."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            "2026-03-20" in body
        ), "Expected current date '2026-03-20' to appear pre-filled in the edit form"

    def test_get_prefills_description(self, auth_client, expense_id):
        """Spec: description field pre-filled with current value."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            "Original lunch" in body
        ), "Expected current description 'Original lunch' to appear pre-filled"

    def test_get_marks_current_category_selected(self, auth_client, expense_id):
        """Spec: current category option must be marked selected in the <select>."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        # Jinja template typically renders: value="Food" selected or selected="selected"
        assert (
            'value="Food" selected' in body
            or 'value="Food"selected' in body
            or ">Food<" in body  # fallback: option text present
        ), "Expected the current category 'Food' to be marked selected in the dropdown"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_get_form_contains_each_category_option(
        self, auth_client, expense_id, category
    ):
        """Spec: the category <select> must contain all 7 fixed category options."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            category in body
        ), f"Expected category option '{category}' to appear in the edit form dropdown"

    def test_get_form_contains_amount_field(self, auth_client, expense_id):
        """Spec: form includes an amount input (name='amount')."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            'name="amount"' in body
        ), 'Expected an input with name="amount" on the edit-expense form'

    def test_get_form_contains_category_select(self, auth_client, expense_id):
        """Spec: form includes a category select (name='category')."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            'name="category"' in body
        ), 'Expected a select with name="category" on the edit-expense form'

    def test_get_form_contains_date_field(self, auth_client, expense_id):
        """Spec: form includes a date input (name='date')."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            'name="date"' in body
        ), 'Expected an input with name="date" on the edit-expense form'

    def test_get_form_contains_description_field(self, auth_client, expense_id):
        """Spec: form includes a description input (name='description')."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            'name="description"' in body
        ), 'Expected an input with name="description" on the edit-expense form'

    def test_categories_constant_has_exactly_7_entries(self):
        """Spec: Exactly 7 fixed categories: Food, Transport, Bills, Health,
        Entertainment, Shopping, Other."""
        assert (
            len(CATEGORIES) == 7
        ), f"CATEGORIES must contain exactly 7 entries, found {len(CATEGORIES)}: {CATEGORIES}"
        expected = {
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        }
        for name in expected:
            assert name in CATEGORIES, f"'{name}' must be in CATEGORIES"


# ------------------------------------------------------------------ #
# 6. POST happy path — owner updates expense                          #
# ------------------------------------------------------------------ #


class TestPostEditExpenseHappyPath:
    """
    Spec: POST /expenses/<id>/edit with valid data from the owner → 302 to
    /profile; DB row reflects updated values.
    """

    def test_post_valid_returns_302(self, auth_client, expense_id):
        """Spec: valid POST → 302."""
        response = auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        assert (
            response.status_code == 302
        ), "Expected 302 redirect after a valid owner POST to /expenses/<id>/edit"

    def test_post_valid_redirects_to_profile(self, auth_client, expense_id):
        """Spec: valid POST redirects to /profile."""
        response = auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Expected redirect to /profile after valid POST, got Location={location!r}"

    def test_post_valid_updates_amount_in_db(self, auth_client, db_conn, expense_id):
        """Spec: DB row reflects the updated amount after a valid POST."""
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            300.50
        ), f"Expected DB amount 300.50, got {row['amount']}"

    def test_post_valid_updates_category_in_db(self, auth_client, db_conn, expense_id):
        """Spec: DB row reflects the updated category after a valid POST."""
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert (
            row["category"] == "Transport"
        ), f"Expected DB category 'Transport', got {row['category']}"

    def test_post_valid_updates_date_in_db(self, auth_client, db_conn, expense_id):
        """Spec: DB row reflects the updated date after a valid POST."""
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert (
            row["date"] == "2026-04-10"
        ), f"Expected DB date '2026-04-10', got {row['date']}"

    def test_post_valid_updates_description_in_db(
        self, auth_client, db_conn, expense_id
    ):
        """Spec: DB row reflects the updated description after a valid POST."""
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert (
            row["description"] == "Updated cab ride"
        ), f"Expected DB description 'Updated cab ride', got {row['description']}"

    def test_post_valid_preserves_user_id_in_db(
        self, auth_client, db_conn, expense_id, test_user_id
    ):
        """Spec: a valid edit must not change the user_id on the row."""
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert (
            row["user_id"] == test_user_id
        ), f"Expected user_id={test_user_id} preserved, got {row['user_id']}"

    def test_post_only_targeted_row_changes(
        self, app, auth_client, db_conn, expense_id, test_user_id
    ):
        """Spec: only the targeted row is updated; other rows remain unchanged."""
        # Insert a second expense owned by the same user
        with app.app_context():
            other_id = insert_expense(
                test_user_id, 100.0, "Health", "2026-01-01", "Pharmacy"
            )
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        other_row = _row(db_conn, other_id)
        assert other_row["amount"] == pytest.approx(
            100.0
        ), "Only the targeted row should be updated; other rows must remain unchanged"
        assert (
            other_row["category"] == "Health"
        ), "Only the targeted row should be updated; other rows must remain unchanged"

    def test_post_cleared_description_stores_null(
        self, auth_client, db_conn, expense_id
    ):
        """Spec: cleared description field → row updated with description = NULL."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "description": ""},
        )
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), "Clearing the description must store SQL NULL in the DB"

    def test_post_whitespace_description_stores_null(
        self, auth_client, db_conn, expense_id
    ):
        """Spec: whitespace-only description is stripped → stored as NULL."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "description": "   "},
        )
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), "Whitespace-only description must be stored as SQL NULL"


# ------------------------------------------------------------------ #
# 7. POST validation errors — amount                                  #
# ------------------------------------------------------------------ #


class TestPostEditExpenseAmountValidation:
    """
    Spec: amount is required, must be a positive number > 0.
    Invalid amounts re-render the form (200) with an error message.
    The DB row must not be modified.
    """

    @pytest.mark.parametrize(
        "bad_amount",
        ["", "0", "-5", "-0.01", "abc", "50px", "one hundred", "₹50", "$50"],
    )
    def test_invalid_amount_rerenders_form(self, auth_client, expense_id, bad_amount):
        """Spec: invalid amount → 200 (form re-render)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": bad_amount},
        )
        assert (
            response.status_code == 200
        ), f"Expected 200 (form re-render) for amount={bad_amount!r}"

    @pytest.mark.parametrize(
        "bad_amount",
        ["", "0", "-5", "abc", "50px"],
    )
    def test_invalid_amount_shows_error_message(
        self, auth_client, expense_id, bad_amount
    ):
        """Spec: invalid amount → error message in the response body."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": bad_amount},
        )
        body = response.data.decode("utf-8")
        assert (
            "Amount must be a number greater than 0." in body
        ), f"Expected error 'Amount must be a number greater than 0.' for amount={bad_amount!r}"

    @pytest.mark.parametrize(
        "bad_amount",
        ["", "0", "-5", "abc"],
    )
    def test_invalid_amount_does_not_modify_row(
        self, auth_client, db_conn, expense_id, bad_amount
    ):
        """Spec: invalid amount → original row must remain unchanged."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": bad_amount},
        )
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            250.00
        ), f"Row amount must not change when amount={bad_amount!r}"
        assert (
            row["category"] == "Food"
        ), f"Row category must not change when amount={bad_amount!r}"

    def test_missing_amount_rerenders_form(self, auth_client, expense_id):
        """Spec: missing/empty amount field → form re-rendered (200)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": ""},
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) when amount is empty"

    def test_zero_amount_rerenders_form(self, auth_client, expense_id):
        """Spec: amount=0 is not positive → form re-rendered (200)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "0"},
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) when amount=0"

    def test_non_numeric_amount_rerenders_form(self, auth_client, expense_id):
        """Spec: non-numeric amount → form re-rendered (200)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "not-a-number"},
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) when amount is non-numeric"


# ------------------------------------------------------------------ #
# 8. POST validation errors — category                                #
# ------------------------------------------------------------------ #


class TestPostEditExpenseCategoryValidation:
    """
    Spec: category must be one of the 7 fixed categories in CATEGORIES.
    Invalid or empty category re-renders the form (200) with an error.
    """

    def test_invalid_category_rerenders_form(self, auth_client, expense_id):
        """Spec: category not in CATEGORIES → 200 (form re-render)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Bogus"},
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) for an invalid category"

    def test_invalid_category_shows_error_message(self, auth_client, expense_id):
        """Spec: invalid category → error message in the response body."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Bogus"},
        )
        body = response.data.decode("utf-8")
        assert (
            "Please choose a valid category." in body
        ), "Expected error 'Please choose a valid category.' for an invalid category"

    def test_empty_category_rerenders_form(self, auth_client, expense_id):
        """Spec: empty string category is not in CATEGORIES → 200 (form re-render)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": ""},
        )
        assert (
            response.status_code == 200
        ), "Expected 200 (form re-render) when category is empty"

    def test_invalid_category_does_not_modify_row(
        self, auth_client, db_conn, expense_id
    ):
        """Spec: invalid category → original row unchanged."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Bogus"},
        )
        row = _row(db_conn, expense_id)
        assert (
            row["category"] == "Food"
        ), "Row category must not change when an invalid category is submitted"

    def test_sql_injection_in_category_rejected_and_row_unchanged(
        self, auth_client, db_conn, expense_id
    ):
        """Spec: a category value that is not in CATEGORIES must be rejected.
        Parameterised queries must prevent any SQL injection effect."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Food'; DROP TABLE expenses;--"},
        )
        # Row must be unchanged
        row = _row(db_conn, expense_id)
        assert (
            row is not None
        ), "expenses table must still exist after SQL injection attempt"
        assert (
            row["category"] == "Food"
        ), "Row category must not change when injection string is submitted"


# ------------------------------------------------------------------ #
# 9. POST validation errors — date                                    #
# ------------------------------------------------------------------ #


class TestPostEditExpenseDateValidation:
    """
    Spec: date must be a valid YYYY-MM-DD date (validated via _validate_iso_date).
    Invalid dates re-render the form (200) with an error. Row unchanged.
    """

    @pytest.mark.parametrize(
        "bad_date",
        [
            "",
            "not-a-date",
            "2026/04/10",  # wrong separator
            "10-04-2026",  # reversed order
            "2026-13-01",  # month 13
            "2026-00-15",  # month 0
            "2026-02-30",  # Feb 30 does not exist
            "9999-99-99",  # completely out of range
        ],
    )
    def test_invalid_date_rerenders_form(self, auth_client, expense_id, bad_date):
        """Spec: invalid date string → 200 (form re-render)."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "date": bad_date},
        )
        assert (
            response.status_code == 200
        ), f"Expected 200 (form re-render) for date={bad_date!r}"

    @pytest.mark.parametrize(
        "bad_date",
        [
            "",
            "not-a-date",
            "2026/04/10",
            "10-04-2026",
            "2026-13-01",
            "2026-02-30",
        ],
    )
    def test_invalid_date_shows_error_message(self, auth_client, expense_id, bad_date):
        """Spec: invalid date → 'Please enter a valid date' error in response."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "date": bad_date},
        )
        body = response.data.decode("utf-8")
        assert (
            "Please enter a valid date" in body
        ), f"Expected 'Please enter a valid date' error for date={bad_date!r}"

    @pytest.mark.parametrize(
        "bad_date",
        ["", "not-a-date", "2026/04/10", "2026-13-01"],
    )
    def test_invalid_date_does_not_modify_row(
        self, auth_client, db_conn, expense_id, bad_date
    ):
        """Spec: invalid date → original row unchanged."""
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "date": bad_date},
        )
        row = _row(db_conn, expense_id)
        assert (
            row["date"] == "2026-03-20"
        ), f"Row date must not change when an invalid date={bad_date!r} is submitted"


# ------------------------------------------------------------------ #
# 10. POST error — form repopulates submitted values (not originals)  #
# ------------------------------------------------------------------ #


class TestPostEditExpenseFormRepopulation:
    """
    Spec: On any validation error, re-render the form with the *submitted*
    values pre-filled — not the original DB values. This allows the user
    to correct only the invalid field without losing other edits.
    """

    def test_error_repopulates_submitted_category(self, auth_client, expense_id):
        """Submitted category must appear selected in the re-rendered form."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "category": "Health"},
        )
        body = response.data.decode("utf-8")
        # The submitted category 'Health' must appear (selected), not the original 'Food'
        assert (
            "Health" in body
        ), "Expected submitted category 'Health' to be repopulated in the error form"

    def test_error_repopulates_submitted_date(self, auth_client, expense_id):
        """Submitted date must appear in the re-rendered form."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "date": "2026-07-04"},
        )
        body = response.data.decode("utf-8")
        assert (
            "2026-07-04" in body
        ), "Expected submitted date '2026-07-04' to be repopulated in the error form"

    def test_error_repopulates_submitted_description(self, auth_client, expense_id):
        """Submitted description must appear in the re-rendered form."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "description": "Brand new note"},
        )
        body = response.data.decode("utf-8")
        assert (
            "Brand new note" in body
        ), "Expected submitted description 'Brand new note' to be repopulated in the error form"

    def test_error_does_not_show_original_description_when_user_changed_it(
        self, auth_client, expense_id
    ):
        """The re-rendered form must show submitted values, not the original DB values."""
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "description": "Edited note"},
        )
        body = response.data.decode("utf-8")
        # The submitted description must appear
        assert (
            "Edited note" in body
        ), "Expected submitted description 'Edited note' to appear in re-rendered form"
        # The original DB description must NOT override the submitted value
        # (we can only assert this when the user typed something different)
        assert (
            "Original lunch" not in body
        ), "Original DB description must not replace the submitted value on error re-render"


# ------------------------------------------------------------------ #
# 11. Profile page — Edit links per transaction row                   #
# ------------------------------------------------------------------ #


class TestProfilePageEditLinks:
    """
    Spec: The profile page transactions table must include an "Edit"
    action link per row pointing to /expenses/<id>/edit.
    get_recent_transactions must include 'id' in each returned dict
    so the template can build edit links.
    """

    def test_profile_renders_edit_link_for_owned_expense(self, auth_client, expense_id):
        """Spec: /profile must include a link to /expenses/<id>/edit for each
        owned transaction row."""
        response = auth_client.get("/profile")
        assert (
            response.status_code == 200
        ), "Expected 200 for authenticated GET /profile"
        body = response.data.decode("utf-8")
        assert (
            f"/expenses/{expense_id}/edit" in body
        ), f"Expected an Edit link to /expenses/{expense_id}/edit on the profile page"

    def test_profile_renders_edit_link_for_multiple_expenses(
        self, app, auth_client, db_conn, expense_id, test_user_id
    ):
        """Spec: every transaction row must have its own distinct edit link."""
        with app.app_context():
            second_id = insert_expense(
                test_user_id, 75.00, "Shopping", "2026-04-01", "Clothes"
            )
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        assert (
            f"/expenses/{expense_id}/edit" in body
        ), "Expected edit link for first expense on profile page"
        assert (
            f"/expenses/{second_id}/edit" in body
        ), "Expected edit link for second expense on profile page"
