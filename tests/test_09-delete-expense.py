"""
tests/test_09-delete-expense.py

Pytest test suite for Step 9: Delete Expense.

All assertions are derived from the feature spec at
.claude/specs/09-delete-expense.md — NOT from the implementation.

Fixture strategy mirrors tests/test_edit_expense.py:
- `app`                 : Flask app wired to a tmp-file SQLite DB via monkeypatch.
- `client`              : Plain (unauthenticated) test client.
- `db_conn`             : Direct SQLite connection to the same temp DB.
- `test_user_id`        : Owner user, inserted fresh per test.
- `other_user_id`       : A second user, used for owner-only enforcement tests.
- `auth_client`         : Client with `test_user_id` already placed in the session.
- `expense_id`          : An expense row owned by `test_user_id`.
- `foreign_expense_id`  : An expense row owned by `other_user_id`.
"""

import sqlite3
import pytest

from app import app as flask_app
from database.db import init_db
from database.queries import delete_expense, insert_expense
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Core fixtures                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_delete.db")
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
            test_user_id, 500.00, "Food", "2026-04-15", "Owner's lunch"
        )


@pytest.fixture
def foreign_expense_id(app, other_user_id):
    """An expense row owned by `other_user_id` (not the authenticated user)."""
    with app.app_context():
        return insert_expense(
            other_user_id, 1200.00, "Bills", "2026-04-10", "Other user's electricity"
        )


def _row(db_conn, eid):
    """Fetch a raw expense row by id (or None if not present)."""
    return db_conn.execute("SELECT * FROM expenses WHERE id = ?", (eid,)).fetchone()


def _expense_count(db_conn):
    """Return total number of expense rows in the table."""
    return db_conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]


# ------------------------------------------------------------------ #
# 1. Unit tests — delete_expense helper                               #
# ------------------------------------------------------------------ #


class TestDeleteExpenseHelper:
    """Direct unit tests for the delete_expense(expense_id, user_id) helper."""

    def test_owner_delete_returns_rowcount_one(self, app, expense_id, test_user_id):
        with app.app_context():
            affected = delete_expense(expense_id, test_user_id)
        assert (
            affected == 1
        ), f"Expected rowcount=1 when owner deletes own expense, got {affected}"

    def test_owner_delete_removes_row_from_db(
        self, app, db_conn, expense_id, test_user_id
    ):
        with app.app_context():
            delete_expense(expense_id, test_user_id)
        row = _row(db_conn, expense_id)
        assert row is None, "Expense row must be gone from DB after owner deletes it"

    def test_non_owner_delete_returns_rowcount_zero(
        self, app, foreign_expense_id, test_user_id
    ):
        """Deleting another user's expense must affect 0 rows."""
        with app.app_context():
            affected = delete_expense(foreign_expense_id, test_user_id)
        assert (
            affected == 0
        ), f"Expected rowcount=0 when non-owner attempts delete, got {affected}"

    def test_non_owner_delete_leaves_row_intact(
        self, app, db_conn, foreign_expense_id, test_user_id
    ):
        with app.app_context():
            delete_expense(foreign_expense_id, test_user_id)
        row = _row(db_conn, foreign_expense_id)
        assert row is not None, "Row belonging to another user must remain intact"
        assert row["amount"] == pytest.approx(1200.00)
        assert row["description"] == "Other user's electricity"

    def test_nonexistent_id_returns_rowcount_zero(self, app, test_user_id):
        with app.app_context():
            affected = delete_expense(99999, test_user_id)
        assert (
            affected == 0
        ), f"Expected rowcount=0 for non-existent expense id, got {affected}"

    def test_nonexistent_id_causes_no_side_effects(
        self, app, db_conn, test_user_id, expense_id
    ):
        """Attempting to delete a missing id must not disturb other rows."""
        count_before = _expense_count(db_conn)
        with app.app_context():
            delete_expense(99999, test_user_id)
        count_after = _expense_count(db_conn)
        assert (
            count_before == count_after
        ), "Expense table row count must not change when deleting a non-existent id"

    def test_idempotency_first_call_returns_one(self, app, expense_id, test_user_id):
        with app.app_context():
            first = delete_expense(expense_id, test_user_id)
        assert first == 1, f"First delete must return rowcount=1, got {first}"

    def test_idempotency_second_call_returns_zero(self, app, expense_id, test_user_id):
        with app.app_context():
            delete_expense(expense_id, test_user_id)
            second = delete_expense(expense_id, test_user_id)
        assert (
            second == 0
        ), f"Second delete on same id must return rowcount=0, got {second}"


# ------------------------------------------------------------------ #
# 2. HTTP method guard — GET must be 405                              #
# ------------------------------------------------------------------ #


class TestDeleteExpenseGetMethod:
    """A destructive action must never be reachable via GET."""

    def test_get_unauthenticated_returns_405(self, client, expense_id):
        response = client.get(f"/expenses/{expense_id}/delete")
        assert (
            response.status_code == 405
        ), "GET to the delete route must return 405 Method Not Allowed"

    def test_get_authenticated_returns_405(self, auth_client, expense_id):
        response = auth_client.get(f"/expenses/{expense_id}/delete")
        assert (
            response.status_code == 405
        ), "GET to the delete route must return 405 even when authenticated"

    def test_get_nonexistent_id_returns_405(self, auth_client):
        response = auth_client.get("/expenses/99999/delete")
        assert (
            response.status_code == 405
        ), "GET to the delete route for a missing id must still return 405"


# ------------------------------------------------------------------ #
# 3. Auth guard — unauthenticated POST                                #
# ------------------------------------------------------------------ #


class TestDeleteExpenseAuthGuard:
    """Unauthenticated POST requests must be blocked and the row must be untouched."""

    def test_post_unauthenticated_returns_302(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/delete")
        assert (
            response.status_code == 302
        ), "Unauthenticated POST to delete must return 302"

    def test_post_unauthenticated_redirects_to_login(self, client, expense_id):
        response = client.post(f"/expenses/{expense_id}/delete")
        location = response.headers.get("Location", "")
        assert (
            "/login" in location
        ), f"Unauthenticated POST must redirect to /login, got Location={location!r}"

    def test_post_unauthenticated_does_not_delete_row(
        self, client, db_conn, expense_id
    ):
        client.post(f"/expenses/{expense_id}/delete")
        row = _row(db_conn, expense_id)
        assert row is not None, "Unauthenticated POST must not delete the expense row"


# ------------------------------------------------------------------ #
# 4. Owner happy path — authenticated owner deletes own expense       #
# ------------------------------------------------------------------ #


class TestDeleteExpenseOwnerHappyPath:
    """Authenticated owner POSTs to delete their own expense."""

    def test_post_owner_returns_302(self, auth_client, expense_id):
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        assert response.status_code == 302, "Owner delete must return a 302 redirect"

    def test_post_owner_redirects_to_profile(self, auth_client, expense_id):
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), f"Owner delete must redirect to /profile, got Location={location!r}"

    def test_post_owner_removes_row_from_db(self, auth_client, db_conn, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        row = _row(db_conn, expense_id)
        assert row is None, "Expense row must be absent from DB after owner deletes it"

    def test_post_owner_success_flash_on_profile(self, auth_client, expense_id):
        """Following the redirect to /profile must show a success flash message."""
        response = auth_client.post(
            f"/expenses/{expense_id}/delete", follow_redirects=True
        )
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert (
            "Expense deleted" in body
        ), "Profile page must display an 'Expense deleted' flash after successful delete"


# ------------------------------------------------------------------ #
# 5. Owner gate — authenticated user tries to delete another user's   #
#    expense                                                          #
# ------------------------------------------------------------------ #


class TestDeleteExpenseOwnerGate:
    """A logged-in user must not be able to delete another user's expense."""

    def test_post_non_owner_returns_302(self, auth_client, foreign_expense_id):
        response = auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        assert response.status_code == 302, "Non-owner delete attempt must return 302"

    def test_post_non_owner_redirects_to_profile(self, auth_client, foreign_expense_id):
        response = auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), "Non-owner delete attempt must redirect to /profile"

    def test_post_non_owner_leaves_row_intact(
        self, auth_client, db_conn, foreign_expense_id
    ):
        auth_client.post(f"/expenses/{foreign_expense_id}/delete")
        row = _row(db_conn, foreign_expense_id)
        assert (
            row is not None
        ), "Another user's expense row must remain intact after a non-owner delete attempt"
        assert row["amount"] == pytest.approx(1200.00)
        assert row["description"] == "Other user's electricity"

    def test_post_non_owner_does_not_leak_expense_description(
        self, auth_client, foreign_expense_id
    ):
        """The response (including the flash) must not reveal the other user's data."""
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert (
            "Other user's electricity" not in body
        ), "Response must not leak the other user's expense description"

    def test_post_non_owner_generic_flash_message(
        self, auth_client, foreign_expense_id
    ):
        """Flash must use the same generic 'not found' wording — do not reveal
        that a row exists but belongs to someone else."""
        response = auth_client.post(
            f"/expenses/{foreign_expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert (
            "Expense not found" in body
        ), "Non-owner delete attempt must produce a generic 'Expense not found' flash"


# ------------------------------------------------------------------ #
# 6. Non-existent expense id                                          #
# ------------------------------------------------------------------ #


class TestDeleteExpenseNotFound:
    """POST to delete an id that does not exist in the database."""

    def test_post_missing_id_returns_302(self, auth_client):
        response = auth_client.post("/expenses/99999/delete")
        assert response.status_code == 302, "Delete of non-existent id must return 302"

    def test_post_missing_id_redirects_to_profile(self, auth_client):
        response = auth_client.post("/expenses/99999/delete")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), "Delete of non-existent id must redirect to /profile"

    def test_post_missing_id_shows_not_found_flash(self, auth_client):
        response = auth_client.post("/expenses/99999/delete", follow_redirects=True)
        body = response.data.decode("utf-8")
        assert (
            "Expense not found" in body
        ), "Profile page must show a generic 'Expense not found' flash for missing id"

    def test_post_missing_id_causes_no_db_side_effects(
        self, auth_client, db_conn, expense_id
    ):
        """Attempting to delete a non-existent id must not change the row count."""
        count_before = _expense_count(db_conn)
        auth_client.post("/expenses/99999/delete")
        count_after = _expense_count(db_conn)
        assert (
            count_before == count_after
        ), "Expense table row count must not change when deleting a non-existent id"


# ------------------------------------------------------------------ #
# 7. Idempotency — second POST on same already-deleted id             #
# ------------------------------------------------------------------ #


class TestDeleteExpenseIdempotency:
    """Submitting the delete form a second time after the row is already gone
    must not raise a 500 or any unhandled error."""

    def test_second_post_returns_302_not_500(self, auth_client, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        assert (
            response.status_code == 302
        ), "Second delete on same id must return 302, not 500"

    def test_second_post_redirects_to_profile(self, auth_client, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        response = auth_client.post(f"/expenses/{expense_id}/delete")
        location = response.headers.get("Location", "")
        assert (
            "/profile" in location
        ), "Second delete on same id must redirect to /profile"

    def test_second_post_shows_not_found_flash(self, auth_client, expense_id):
        auth_client.post(f"/expenses/{expense_id}/delete")
        response = auth_client.post(
            f"/expenses/{expense_id}/delete", follow_redirects=True
        )
        body = response.data.decode("utf-8")
        assert (
            "Expense not found" in body
        ), "Second delete on same id must show 'Expense not found' flash, not a server error"


# ------------------------------------------------------------------ #
# 8. Template tests — delete form on /profile                         #
# ------------------------------------------------------------------ #


class TestProfileDeleteForm:
    """The profile transactions table renders a per-row delete button that opens
    a confirmation modal. The modal contains a single hidden POST form whose
    action is set in JS from the button's data attributes."""

    def test_profile_contains_delete_url_for_row(self, auth_client, expense_id):
        """Each transaction row must expose the delete URL so the confirm modal
        can submit to it after the user confirms."""
        response = auth_client.get("/profile")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert (
            f"/expenses/{expense_id}/delete" in body
        ), f"Expected the delete URL /expenses/{expense_id}/delete in the profile page"

    def test_profile_renders_modal_form_with_post_method(self, auth_client, expense_id):
        """A single hidden POST form lives in the confirmation modal so the
        delete request cannot be triggered by a GET-style link click."""
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        assert 'id="deleteModalForm"' in body, "Confirmation modal must contain a form"
        # Locate the modal form tag and verify its method is POST
        idx = body.find('id="deleteModalForm"')
        window = body[max(0, idx - 200) : idx + 200].lower()
        assert "method=" in window, "Modal form must specify a method attribute"
        assert "post" in window, "Modal form method must be POST"

    def test_profile_delete_button_opens_confirm_modal(self, auth_client, expense_id):
        """The delete button must be wired to open the confirmation modal —
        identified by the .js-delete-btn class and the data-delete-url attribute
        carrying the row's delete URL."""
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        assert (
            "js-delete-btn" in body
        ), "Delete button must carry the js-delete-btn hook class"
        assert (
            f'data-delete-url="/expenses/{expense_id}/delete"' in body
        ), "Delete button must carry its row's delete URL in data-delete-url"

    def test_profile_delete_button_has_aria_label(self, auth_client, expense_id):
        """The delete button must have an aria-label that includes both the
        expense amount and the date for screen-reader accessibility."""
        response = auth_client.get("/profile")
        body = response.data.decode("utf-8")
        # The expense was inserted with amount=500.0 and date=2026-04-15
        assert (
            "aria-label" in body
        ), "Profile page must contain at least one aria-label on delete buttons"
        assert (
            "2026-04-15" in body
        ), "Delete button aria-label must reference the expense date (2026-04-15)"
        import re

        aria_labels = re.findall(r'aria-label="([^"]*)"', body)
        matching = [lbl for lbl in aria_labels if "500" in lbl and "2026-04-15" in lbl]
        assert matching, (
            "Expected an aria-label mentioning both the amount (500) and the date "
            "(2026-04-15) on the delete button. "
            f"aria-labels found: {aria_labels}"
        )
