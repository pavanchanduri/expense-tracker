"""
tests/test_delete_expense.py

Pytest test suite for Step 9: Delete Expense.

All assertions are derived from the feature spec at
.claude/specs/09-delete-expense.md — NOT from the implementation.

Fixture strategy mirrors tests/test_edit_expense.py:
- `app`            : Flask app wired to a temp-file SQLite DB.
- `client`         : Plain (unauthenticated) test client.
- `db_conn`        : Direct SQLite connection to the same temp DB.
- `test_user_id`   : One owner user, inserted fresh per test.
- `other_user_id`  : A second user, used for owner-only enforcement tests.
- `auth_client`    : Client with `test_user_id` placed in the session.
- `expense_id`     : An expense row owned by `test_user_id`.
- `foreign_expense_id` : An expense row owned by `other_user_id`.
"""

import pytest

from database.queries import delete_expense, insert_expense
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Core fixtures — `app`, `client`, `db_conn` live in conftest.py.     #
# ------------------------------------------------------------------ #


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
            test_user_id, 250.00, "Food", "2026-03-20", "Lunch to delete"
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


# ------------------------------------------------------------------ #
# 1. Unit tests — delete_expense                                      #
# ------------------------------------------------------------------ #


class TestDeleteExpenseHelper:

    def test_owner_delete_returns_one(self, app, expense_id, test_user_id):
        with app.app_context():
            rows = delete_expense(expense_id, test_user_id)
        assert rows == 1, f"Expected rowcount=1 for owner delete, got {rows}"

    def test_owner_delete_removes_row(self, app, db_conn, expense_id, test_user_id):
        with app.app_context():
            delete_expense(expense_id, test_user_id)
        assert (
            _row(db_conn, expense_id) is None
        ), "Row must be gone from the DB after owner delete"

    def test_non_owner_delete_returns_zero(self, app, foreign_expense_id, test_user_id):
        """A delete scoped to the wrong user_id must affect 0 rows."""
        with app.app_context():
            rows = delete_expense(foreign_expense_id, test_user_id)
        assert (
            rows == 0
        ), f"Expected rowcount=0 when deleting another user's row, got {rows}"

    def test_non_owner_delete_leaves_row_intact(
        self, app, db_conn, foreign_expense_id, test_user_id
    ):
        with app.app_context():
            delete_expense(foreign_expense_id, test_user_id)
        row = _row(db_conn, foreign_expense_id)
        assert row is not None, "Another user's row must not be deleted"
        assert row["amount"] == pytest.approx(999.00)
        assert row["category"] == "Bills"

    def test_missing_id_returns_zero(self, app, test_user_id):
        with app.app_context():
            rows = delete_expense(99999, test_user_id)
        assert rows == 0, "Deleting a non-existent id must return rowcount=0"

    def test_repeat_delete_is_idempotent(self, app, db_conn, expense_id, test_user_id):
        with app.app_context():
            first = delete_expense(expense_id, test_user_id)
            second = delete_expense(expense_id, test_user_id)
        assert first == 1
        assert second == 0
        assert _row(db_conn, expense_id) is None


# ------------------------------------------------------------------ #
# 2. Route — GET is not allowed                                       #
# ------------------------------------------------------------------ #


class TestDeleteExpenseGetForbidden:
    """Destructive actions must not be reachable via GET — even when the user
    is authenticated and owns the row."""

    def test_get_unauthenticated_returns_405(self, client, expense_id):
        response = client.get(f"/expenses/{expense_id}/delete")
        assert response.status_code == 405

    def test_get_authenticated_returns_405(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/delete")
        assert response.status_code == 405

    def test_get_does_not_delete_row(self, auth_client, db_conn, expense_id):
        auth_client.get(f"/expenses/{expense_id}/delete")
        assert _row(db_conn, expense_id) is not None, "GET must never delete a row"


# ------------------------------------------------------------------ #
# 3. Route — POST auth guard                                          #
# ------------------------------------------------------------------ #


class TestDeleteExpenseAuthGuard:

    def test_post_unauthenticated_returns_302(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/delete")
        assert response.status_code == 302

    def test_post_unauthenticated_redirects_to_login(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/delete")
        assert "/login" in response.headers.get("Location", "")

    def test_post_unauthenticated_does_not_delete_row(
        self, client, db_conn, expense_id
    ):
        client.post(f"/expenses/{expense_id}/delete")
        assert (
            _row(db_conn, expense_id) is not None
        ), "Unauthenticated POST must not delete the row"


# ------------------------------------------------------------------ #
# 4. Route — POST happy path (owner)                                  #
# ------------------------------------------------------------------ #


class TestDeleteExpenseOwnerHappyPath:

    def test_post_owner_returns_302(self, auth_client, expense_id):
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        assert response.status_code == 302

    def test_post_owner_redirects_to_profile(self, auth_client, expense_id):
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        assert "/profile" in response.headers.get("Location", "")

    def test_post_owner_removes_row(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        assert (
            _row(db_conn, expense_id) is None
        ), "Owner POST must remove the row from the DB"

    def test_post_owner_shows_success_flash(self, auth_client, expense_id):
        """Following the redirect must show a success flash on /profile."""
        response = auth_client.post(
            f"/expenses/{expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert "Expense deleted" in body, "Expected success flash on /profile"


# ------------------------------------------------------------------ #
# 5. Route — POST owner gate (non-owner cannot delete)                #
# ------------------------------------------------------------------ #


class TestDeleteExpenseOwnerGate:

    def test_post_non_owner_returns_302(self, auth_client, foreign_expense_id):
        response = auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        assert response.status_code == 302

    def test_post_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        response = auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        assert "/profile" in response.headers.get("Location", "")

    def test_post_non_owner_does_not_delete_row(
        self, auth_client, db_conn, foreign_expense_id
    ):
        auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        row = _row(db_conn, foreign_expense_id)
        assert row is not None, "Another user's row must not be deleted"
        assert row["amount"] == pytest.approx(999.00)
        assert row["description"] == "Other user's bill"

    def test_post_non_owner_does_not_leak_data(self, auth_client, foreign_expense_id):
        """The response on a non-owner attempt must not contain the other
        user's expense description."""
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert "Other user's bill" not in body


# ------------------------------------------------------------------ #
# 6. Route — POST against a non-existent id                           #
# ------------------------------------------------------------------ #


class TestDeleteExpenseMissingId:

    def test_post_missing_id_returns_302(self, auth_client):
        response = auth_client.post("/expenses/99999/delete")
        assert response.status_code == 302

    def test_post_missing_id_redirects_to_profile(self, auth_client):
        response = auth_client.post("/expenses/99999/delete")
        assert "/profile" in response.headers.get("Location", "")

    def test_post_missing_id_shows_not_found_flash(self, auth_client):
        response = auth_client.post("/expenses/99999/delete", follow_redirects=True)
        body = response.data.decode("utf-8")
        assert "Expense not found" in body


# ------------------------------------------------------------------ #
# 7. Route — idempotency (second delete of same id)                   #
# ------------------------------------------------------------------ #


class TestDeleteExpenseIdempotency:

    def test_second_delete_returns_302_not_500(self, auth_client, db_conn, expense_id):
        first = auth_client.post(f"/expenses/{expense_id}/delete")
        assert first.status_code == 302
        assert _row(db_conn, expense_id) is None

        second = auth_client.post(f"/expenses/{expense_id}/delete")
        assert (
            second.status_code == 302
        ), "Re-deleting an already-deleted id must redirect, not 500"

    def test_second_delete_shows_not_found_flash(self, auth_client, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        response = auth_client.post(
            f"/expenses/{expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert "Expense not found" in body


# ------------------------------------------------------------------ #
# 8. Profile page — delete button per row                             #
# ------------------------------------------------------------------ #


class TestProfilePageDeleteButton:

    def test_profile_renders_delete_button_for_owned_row(self, auth_client, expense_id):
        """Each row renders a delete button carrying the delete URL in a data attribute,
        plus a single hidden modal form that will POST to it after confirmation."""
        response = auth_client.get("/profile")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert (
            f'data-delete-url="/expenses/{expense_id}/delete"' in body
        ), "Expected a delete button per row carrying the delete URL"

    def test_profile_renders_confirm_modal_form(self, auth_client, expense_id):
        """A single hidden POST form lives in the confirmation modal; its action is
        set by JS when a row's delete button is clicked."""
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        assert 'id="deleteModalForm"' in body
        assert 'method="POST"' in body, "Modal form must use POST"

    def test_profile_delete_button_has_aria_label(self, auth_client, expense_id):
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        assert (
            "Delete ₹250.00 expense on 2026-03-20" in body
        ), "Delete button must have an aria-label mentioning amount and date"
