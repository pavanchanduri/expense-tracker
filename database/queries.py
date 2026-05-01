"""Pure SQLite query helpers for the profile page.

No Flask imports. Each function opens a connection via get_db(), runs
parameterised queries, and closes the connection before returning.
"""

from datetime import datetime
from database.db import get_db


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
def get_summary_stats(user_id):
    """Return {'total_spent', 'transaction_count', 'top_category'}."""
    db = get_db()
    try:
        totals = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n "
            "FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        top = db.execute(
            "SELECT category FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id,),
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
def get_recent_transactions(user_id, limit=10):
    """Return list of {'date', 'description', 'category', 'amount'} dicts,
    newest first, capped at `limit`. Empty list when no expenses."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT date, description, category, amount "
            "FROM expenses WHERE user_id = ? "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [
            {
                "date": row["date"],
                "description": row["description"] if row["description"] is not None else "",
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
def get_category_breakdown(user_id):
    """Return list of {'name', 'amount', 'pct'} dicts ordered by amount
    desc; integer pct values sum to 100. Empty list when no expenses."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT category AS name, SUM(amount) AS amount "
            "FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY amount DESC",
            (user_id,),
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
