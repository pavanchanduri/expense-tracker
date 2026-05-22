"""Pure SQLite query helpers for the profile page.

No Flask imports. Each function opens a connection via get_db(), runs
parameterised queries, and closes the connection before returning.
"""

from datetime import datetime
from database.db import get_db

CATEGORIES = (
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
)


def _clean_description(value):
    """Trim, cap at 200 chars, and return None when the result is blank."""
    return (value or "").strip()[:200] or None


# ------------------------------------------------------------------ #
# Step 7 — write helper                                                #
# ------------------------------------------------------------------ #
def insert_expense(user_id, amount, category, expense_date, description):
    """Insert a new expense row and return its id.

    `description` is trimmed, capped at 200 chars, and stored as NULL when blank.
    """
    cleaned = _clean_description(description)
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, cleaned),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Step 8 — read + update helpers                                       #
# ------------------------------------------------------------------ #
def get_expense_by_id(expense_id, user_id):
    """Return the expense row as a dict scoped to the owning user, or None.

    Scoping by `user_id` ensures a logged-in user cannot read another user's
    expense by guessing its id.
    """
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "amount": float(row["amount"]),
            "category": row["category"],
            "date": row["date"],
            "description": row["description"],
        }
    finally:
        db.close()


def update_expense(expense_id, user_id, amount, category, expense_date, description):
    """Update an expense the user owns. Returns the number of rows affected.

    Returns 0 when the row does not exist or belongs to another user, so the
    caller can detect ownership mismatches without a separate read.
    """
    cleaned = _clean_description(description)
    db = get_db()
    try:
        cursor = db.execute(
            "UPDATE expenses "
            "SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, category, expense_date, cleaned, expense_id, user_id),
        )
        db.commit()
        return cursor.rowcount
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Subagent 2 — user info                                              #
# ------------------------------------------------------------------ #
def get_user_by_id(user_id):
    """Return {'name', 'email', 'member_since'} or None."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        member_since = datetime.strptime(
            row["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %Y")
        return {
            "name": row["name"],
            "email": row["email"],
            "member_since": member_since,
        }
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Subagent 2 — summary stats                                          #
# ------------------------------------------------------------------ #
def get_summary_stats(user_id, date_from=None, date_to=None):
    """Return {'total_spent', 'transaction_count', 'top_category'}.

    When both date_from and date_to are provided (ISO YYYY-MM-DD strings),
    results are scoped to expenses with date BETWEEN date_from AND date_to.
    """
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])

    db = get_db()
    try:
        totals = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n "
            "FROM expenses " + where,
            params,
        ).fetchone()
        top = db.execute(
            "SELECT category FROM expenses " + where + " "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            params,
        ).fetchone()
        return {
            "total_spent": float(totals["total"]),
            "transaction_count": int(totals["n"]),
            "top_category": top["category"] if top is not None else "—",
        }
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Subagent 1 — recent transactions                                    #
# ------------------------------------------------------------------ #
def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    """Return list of {'id', 'date', 'description', 'category', 'amount'} dicts,
    newest first, capped at `limit`. Empty list when no expenses.

    When both date_from and date_to are provided (ISO YYYY-MM-DD strings),
    results are scoped to expenses with date BETWEEN date_from AND date_to.
    """
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])
    params.append(limit)

    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, date, description, category, amount "
            "FROM expenses " + where + " "
            "ORDER BY date DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "id": row["id"],
                "date": row["date"],
                "description": (
                    row["description"] if row["description"] is not None else ""
                ),
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Subagent 3 — category breakdown                                     #
# ------------------------------------------------------------------ #
def get_category_breakdown(user_id, date_from=None, date_to=None):
    """Return list of {'name', 'amount', 'pct'} dicts ordered by amount
    desc; integer pct values sum to 100. Empty list when no expenses.

    When both date_from and date_to are provided (ISO YYYY-MM-DD strings),
    results are scoped to expenses with date BETWEEN date_from AND date_to.
    """
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])

    db = get_db()
    try:
        rows = db.execute(
            "SELECT category AS name, SUM(amount) AS amount "
            "FROM expenses " + where + " "
            "GROUP BY category ORDER BY amount DESC",
            params,
        ).fetchall()
        if not rows:
            return []

        grand_total = sum(row["amount"] for row in rows)
        if grand_total == 0:
            return [
                {"name": row["name"], "amount": float(row["amount"]), "pct": 0}
                for row in rows
            ]

        pcts = [int(row["amount"] / grand_total * 100) for row in rows]
        leftover = 100 - sum(pcts)
        pcts[0] += leftover

        return [
            {"name": row["name"], "amount": float(row["amount"]), "pct": pcts[i]}
            for i, row in enumerate(rows)
        ]
    finally:
        db.close()
