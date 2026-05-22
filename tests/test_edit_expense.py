"""
tests/test_edit_expense.py

Pytest test suite for Step 8: Edit Expense.

All assertions are derived from the feature spec at
.claude/specs/08-edit-expense.md — NOT from the implementation.

Fixture strategy mirrors tests/test_add_expense.py:
- `app`            : Flask app wired to a temp-file SQLite DB.
- `client`         : Plain (unauthenticated) test client.
- `db_conn`        : Direct SQLite connection to the same temp DB.
- `test_user_id`   : One owner user, inserted fresh per test.
- `other_user_id`  : A second user, used for owner-only enforcement tests.
- `auth_client`    : Client with `test_user_id` placed in the session.
- `expense_id`     : An expense row owned by `test_user_id`.
- `foreign_expense_id` : An expense row owned by `other_user_id`.
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
    db_file = str(tmp_path / "test_expenses.db")
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
    return _create_user(db_conn, "Owner User", "owner@example.com")


@pytest.fixture
def other_user_id(db_conn):
    return _create_user(db_conn, "Other User", "other@example.com")


@pytest.fixture
def auth_client(client, test_user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = test_user_id
        sess["user_name"] = "Owner User"
    return client


@pytest.fixture
def expense_id(app, test_user_id):
    """An expense row owned by `test_user_id`."""
    with app.app_context():
        return insert_expense(
            test_user_id, 250.00, "Food", "2026-03-20", "Original lunch"
        )


@pytest.fixture
def foreign_expense_id(app, other_user_id):
    """An expense row owned by `other_user_id` (not the authenticated user)."""
    with app.app_context():
        return insert_expense(
            other_user_id, 999.00, "Bills", "2026-03-15", "Other user's bill"
        )


def _row(db_conn, expense_id):
    return db_conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()


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

    def test_returns_dict_for_owner(self, app, expense_id, test_user_id):
        with app.app_context():
            row = get_expense_by_id(expense_id, test_user_id)
        assert row is not None, "Expected a dict for the owning user"
        assert row["id"] == expense_id
        assert row["user_id"] == test_user_id
        assert row["amount"] == pytest.approx(250.00)
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Original lunch"

    def test_returns_none_for_non_owner(self, app, foreign_expense_id, test_user_id):
        """A user must not be able to load another user's expense by id."""
        with app.app_context():
            row = get_expense_by_id(foreign_expense_id, test_user_id)
        assert (
            row is None
        ), "Expected None when loading an expense owned by a different user"

    def test_returns_none_for_missing_id(self, app, test_user_id):
        with app.app_context():
            row = get_expense_by_id(99999, test_user_id)
        assert row is None, "Expected None for a non-existent expense id"


# ------------------------------------------------------------------ #
# 2. Unit tests — update_expense                                      #
# ------------------------------------------------------------------ #


class TestUpdateExpenseHelper:

    def test_owner_update_returns_one(self, app, expense_id, test_user_id):
        with app.app_context():
            rows = update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "New"
            )
        assert rows == 1, f"Expected rowcount=1 for owner update, got {rows}"

    def test_owner_update_writes_new_values(
        self, app, db_conn, expense_id, test_user_id
    ):
        with app.app_context():
            update_expense(
                expense_id, test_user_id, 400.0, "Bills", "2026-05-01", "New"
            )
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(400.0)
        assert row["category"] == "Bills"
        assert row["date"] == "2026-05-01"
        assert row["description"] == "New"

    def test_non_owner_update_returns_zero(self, app, foreign_expense_id, test_user_id):
        """An update scoped to the wrong user_id must affect 0 rows."""
        with app.app_context():
            rows = update_expense(
                foreign_expense_id, test_user_id, 1.0, "Food", "2026-05-01", "x"
            )
        assert (
            rows == 0
        ), f"Expected rowcount=0 when updating another user's row, got {rows}"

    def test_non_owner_update_leaves_row_unchanged(
        self, app, db_conn, foreign_expense_id, test_user_id
    ):
        with app.app_context():
            update_expense(
                foreign_expense_id, test_user_id, 1.0, "Food", "2026-05-01", "x"
            )
        row = _row(db_conn, foreign_expense_id)
        assert row["amount"] == pytest.approx(999.00)
        assert row["category"] == "Bills"
        assert row["date"] == "2026-03-15"
        assert row["description"] == "Other user's bill"

    def test_update_with_none_description_stores_null(
        self, app, db_conn, expense_id, test_user_id
    ):
        with app.app_context():
            update_expense(expense_id, test_user_id, 50.0, "Food", "2026-03-20", None)
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), f"Expected NULL description when None passed, got {row['description']!r}"

    def test_update_with_blank_description_stores_null(
        self, app, db_conn, expense_id, test_user_id
    ):
        with app.app_context():
            update_expense(expense_id, test_user_id, 50.0, "Food", "2026-03-20", "   ")
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), "Whitespace-only description must be stored as NULL"


# ------------------------------------------------------------------ #
# 3. Auth guard — unauthenticated access                              #
# ------------------------------------------------------------------ #


class TestEditExpenseAuthGuard:

    def test_get_unauthenticated_returns_302(self, client, expense_id):
        response = client.get(f"/expenses/{expense_id}/edit")
        assert response.status_code == 302

    def test_get_unauthenticated_redirects_to_login(self, client, expense_id):
        response = client.get(f"/expenses/{expense_id}/edit")
        assert "/login" in response.headers.get("Location", "")

    def test_post_unauthenticated_returns_302(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        assert response.status_code == 302

    def test_post_unauthenticated_redirects_to_login(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        assert "/login" in response.headers.get("Location", "")

    def test_post_unauthenticated_does_not_modify_row(
        self, client, db_conn, expense_id
    ):
        client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            250.00
        ), "Unauthenticated POST must not modify the row"
        assert row["category"] == "Food"


# ------------------------------------------------------------------ #
# 4. Owner gate — non-owner access redirects to /profile              #
# ------------------------------------------------------------------ #


class TestEditExpenseOwnerGate:

    def test_get_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        assert response.status_code == 302
        assert "/profile" in response.headers.get("Location", "")

    def test_get_non_owner_does_not_render_form(self, auth_client, foreign_expense_id):
        """Foreign row data must not appear in the response body."""
        response = auth_client.get(f"/expenses/{foreign_expense_id}/edit")
        body = response.data.decode("utf-8")
        assert "Other user's bill" not in body
        assert "<form" not in body.lower()

    def test_post_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/edit", data=_VALID_EDIT
        )
        assert response.status_code == 302
        assert "/profile" in response.headers.get("Location", "")

    def test_post_non_owner_does_not_modify_row(
        self, auth_client, db_conn, foreign_expense_id
    ):
        auth_client.post(f"/expenses/{foreign_expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, foreign_expense_id)
        assert row["amount"] == pytest.approx(999.00)
        assert row["category"] == "Bills"
        assert row["date"] == "2026-03-15"
        assert row["description"] == "Other user's bill"

    def test_get_missing_expense_redirects_to_profile(self, auth_client):
        response = auth_client.get("/expenses/99999/edit")
        assert response.status_code == 302
        assert "/profile" in response.headers.get("Location", "")

    def test_post_missing_expense_redirects_to_profile(self, auth_client):
        response = auth_client.post("/expenses/99999/edit", data=_VALID_EDIT)
        assert response.status_code == 302
        assert "/profile" in response.headers.get("Location", "")


# ------------------------------------------------------------------ #
# 5. GET happy path — owner sees pre-filled form                      #
# ------------------------------------------------------------------ #


class TestGetEditExpenseAuthenticated:

    def test_get_returns_200(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        assert response.status_code == 200

    def test_get_renders_post_form(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8").lower()
        assert "<form" in body
        assert 'method="post"' in body

    def test_get_form_action_targets_edit_route(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert f"/expenses/{expense_id}/edit" in body

    def test_get_prefills_amount(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert "250.0" in body, "Expected current amount pre-filled in the form"

    def test_get_prefills_date(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert "2026-03-20" in body, "Expected current date pre-filled in the form"

    def test_get_prefills_description(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            "Original lunch" in body
        ), "Expected current description pre-filled in the form"

    def test_get_marks_current_category_selected(self, auth_client, expense_id):
        """The current category option must be marked selected."""
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            'value="Food" selected' in body or 'value="Food"selected' in body
        ), "Expected the current category ('Food') to be marked selected"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_get_form_contains_each_category_option(
        self, auth_client, expense_id, category
    ):
        response = auth_client.get(f"/expenses/{expense_id}/edit")
        body = response.data.decode("utf-8")
        assert (
            category in body
        ), f"Expected category option '{category}' in the edit form"


# ------------------------------------------------------------------ #
# 6. POST happy path — owner updates expense                          #
# ------------------------------------------------------------------ #


class TestPostEditExpenseHappyPath:

    def test_post_valid_redirects_to_profile(self, auth_client, expense_id):
        response = auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        assert response.status_code == 302
        assert "/profile" in response.headers.get("Location", "")

    def test_post_valid_updates_amount(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(300.50)

    def test_post_valid_updates_category(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["category"] == "Transport"

    def test_post_valid_updates_date(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["date"] == "2026-04-10"

    def test_post_valid_updates_description(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["description"] == "Updated cab ride"

    def test_post_valid_preserves_user_id(
        self, auth_client, db_conn, expense_id, test_user_id
    ):
        auth_client.post(f"/expenses/{expense_id}/edit", data=_VALID_EDIT)
        row = _row(db_conn, expense_id)
        assert row["user_id"] == test_user_id

    def test_post_cleared_description_stores_null(
        self, auth_client, db_conn, expense_id
    ):
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "description": ""},
        )
        row = _row(db_conn, expense_id)
        assert (
            row["description"] is None
        ), "Clearing the description must store SQL NULL"


# ------------------------------------------------------------------ #
# 7. POST validation errors — amount                                  #
# ------------------------------------------------------------------ #


class TestPostEditExpenseAmountValidation:

    @pytest.mark.parametrize("bad_amount", ["", "0", "-5", "abc", "50px"])
    def test_invalid_amount_rerenders_form(self, auth_client, expense_id, bad_amount):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": bad_amount},
        )
        assert (
            response.status_code == 200
        ), f"Expected form re-render for amount={bad_amount!r}"
        body = response.data.decode("utf-8")
        assert "Amount must be a number greater than 0." in body

    @pytest.mark.parametrize("bad_amount", ["", "0", "-5", "abc"])
    def test_invalid_amount_does_not_modify_row(
        self, auth_client, db_conn, expense_id, bad_amount
    ):
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": bad_amount},
        )
        row = _row(db_conn, expense_id)
        assert row["amount"] == pytest.approx(
            250.00
        ), f"Row must not change when amount={bad_amount!r}"
        assert row["category"] == "Food"


# ------------------------------------------------------------------ #
# 8. POST validation errors — category                                #
# ------------------------------------------------------------------ #


class TestPostEditExpenseCategoryValidation:

    def test_invalid_category_rerenders_form(self, auth_client, expense_id):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Bogus"},
        )
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert "Please choose a valid category." in body

    def test_empty_category_rerenders_form(self, auth_client, expense_id):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": ""},
        )
        assert response.status_code == 200

    def test_invalid_category_does_not_modify_row(
        self, auth_client, db_conn, expense_id
    ):
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "category": "Bogus"},
        )
        row = _row(db_conn, expense_id)
        assert row["category"] == "Food"


# ------------------------------------------------------------------ #
# 9. POST validation errors — date                                    #
# ------------------------------------------------------------------ #


class TestPostEditExpenseDateValidation:

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
    def test_invalid_date_rerenders_form(self, auth_client, expense_id, bad_date):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "date": bad_date},
        )
        assert (
            response.status_code == 200
        ), f"Expected form re-render for date={bad_date!r}"
        body = response.data.decode("utf-8")
        assert "Please enter a valid date" in body

    def test_invalid_date_does_not_modify_row(self, auth_client, db_conn, expense_id):
        auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "date": "not-a-date"},
        )
        row = _row(db_conn, expense_id)
        assert row["date"] == "2026-03-20"


# ------------------------------------------------------------------ #
# 10. POST error — form repopulates submitted values                  #
# ------------------------------------------------------------------ #


class TestPostEditExpenseFormRepopulation:
    """Spec: on validation error, re-render the form with the *submitted* values
    (not the original DB values)."""

    def test_error_repopulates_submitted_category(self, auth_client, expense_id):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "category": "Health"},
        )
        body = response.data.decode("utf-8")
        assert 'value="Health" selected' in body or 'value="Health"selected' in body

    def test_error_repopulates_submitted_date(self, auth_client, expense_id):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "date": "2026-07-04"},
        )
        body = response.data.decode("utf-8")
        assert "2026-07-04" in body

    def test_error_repopulates_submitted_description(self, auth_client, expense_id):
        response = auth_client.post(
            f"/expenses/{expense_id}/edit",
            data={**_VALID_EDIT, "amount": "-5", "description": "Brand new note"},
        )
        body = response.data.decode("utf-8")
        assert "Brand new note" in body


# ------------------------------------------------------------------ #
# 11. Profile page — Edit links per row                               #
# ------------------------------------------------------------------ #


class TestProfilePageEditLinks:

    def test_profile_renders_edit_link_for_owned_row(self, auth_client, expense_id):
        """The transactions table on /profile must include an edit link for
        each of the user's own expenses."""
        response = auth_client.get("/profile")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert (
            f"/expenses/{expense_id}/edit" in body
        ), "Expected an Edit link to /expenses/<id>/edit on the profile page"
