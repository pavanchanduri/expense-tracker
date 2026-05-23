"""Pure SQLite query helpers.

No Flask imports. Each function opens a connection via get_db(), runs
parameterised queries, and closes the connection before returning.
"""

from calendar import monthrange
from datetime import date, datetime

from werkzeug.security import generate_password_hash

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


# ------------------------------------------------------------------ #
# Users                                                                #
# ------------------------------------------------------------------ #
def create_user(name, email, password):
    """Hash password and insert a new user. Returns the new user id.

    Raises sqlite3.IntegrityError if email is already taken.
    """
    db = get_db()
    try:
        password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        cursor = db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        db.close()


def get_user_by_email(email):
    """Return the user row for the given email, or None if not found."""
    db = get_db()
    try:
        return db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        db.close()


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
# Step 9 — delete helper                                              #
# ------------------------------------------------------------------ #
def delete_expense(expense_id, user_id):
    """Delete an expense the user owns. Returns the number of rows affected.

    Returns 0 when the row does not exist or belongs to another user, so the
    caller can detect ownership mismatches without a separate read.
    """
    db = get_db()
    try:
        cursor = db.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        db.commit()
        return cursor.rowcount
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Step 10 — export helper                                             #
# ------------------------------------------------------------------ #
def get_expenses_for_export(user_id, date_from=None, date_to=None):
    """Return every expense owned by `user_id`, newest first, with no row cap.

    `date_from` / `date_to` follow the Step-6 both-or-neither contract: when
    only one side is supplied the date filter is ignored. Both must already be
    validated ISO YYYY-MM-DD strings — this helper trusts its caller.
    """
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])

    db = get_db()
    try:
        rows = db.execute(
            "SELECT date, description, category, amount "
            "FROM expenses " + where + " "
            "ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
        return [
            {
                "date": row["date"],
                "description": (
                    row["description"] if row["description"] is not None else ""
                ),
                "category": row["category"],
                "amount": float(row["amount"]),
            }
            for row in rows
        ]
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


# ------------------------------------------------------------------ #
# Step 11 — Analytics                                                  #
# ------------------------------------------------------------------ #
_WEEKDAY_ORDER = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# SQLite's strftime('%w', ...) is 0=Sun..6=Sat; remap to Mon→Sun.
_SQLITE_WEEKDAY_TO_LABEL = {
    "0": "Sun",
    "1": "Mon",
    "2": "Tue",
    "3": "Wed",
    "4": "Thu",
    "5": "Fri",
    "6": "Sat",
}


def get_monthly_trend(user_id, today, months=12):
    """Return `months` calendar-month buckets ending with the month of `today`.

    Each entry is `{"month": "YYYY-MM", "label": "May", "amount": float}`,
    oldest first. Months with zero spend are present with `amount = 0.0`
    so the chart always has a fixed-width skeleton. `today` is injected
    (not derived from `date.today()`) so tests can pass a fixed date.
    """
    skeleton = []
    cursor = date(today.year, today.month, 1)
    for _ in range(months):
        skeleton.append(cursor)
        # Step one month back, handling January → previous-year December.
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    skeleton.reverse()

    earliest_iso = skeleton[0].isoformat()
    db = get_db()
    try:
        rows = db.execute(
            "SELECT strftime('%Y-%m', date) AS m, SUM(amount) AS s "
            "FROM expenses WHERE user_id = ? AND date >= ? "
            "GROUP BY m",
            (user_id, earliest_iso),
        ).fetchall()
    finally:
        db.close()

    totals = {row["m"]: float(row["s"]) for row in rows}
    return [
        {
            "month": d.strftime("%Y-%m"),
            "label": d.strftime("%b"),
            "amount": totals.get(d.strftime("%Y-%m"), 0.0),
        }
        for d in skeleton
    ]


def get_weekday_breakdown(user_id, date_from=None, date_to=None):
    """Return seven `{"weekday", "amount"}` dicts in Mon → Sun order.

    Same both-or-neither `date_from` / `date_to` semantics as the other
    Step-6 helpers. Days with no spend appear with `amount = 0.0`.
    """
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])

    db = get_db()
    try:
        rows = db.execute(
            "SELECT strftime('%w', date) AS w, SUM(amount) AS s "
            "FROM expenses " + where + " GROUP BY w",
            params,
        ).fetchall()
    finally:
        db.close()

    totals = {_SQLITE_WEEKDAY_TO_LABEL[row["w"]]: float(row["s"]) for row in rows}
    return [
        {"weekday": label, "amount": totals.get(label, 0.0)} for label in _WEEKDAY_ORDER
    ]


def get_top_expenses(user_id, limit=5, date_from=None, date_to=None):
    """Return the `limit` largest single expenses, scoped to the user.

    Ordered by `amount DESC, date DESC`. Same both-or-neither
    `date_from` / `date_to` semantics as the other Step-6 helpers.
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
            "ORDER BY amount DESC, date DESC LIMIT ?",
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
                "amount": float(row["amount"]),
            }
            for row in rows
        ]
    finally:
        db.close()


def get_period_comparison(user_id, today):
    """Compare month-to-date vs the same span in the prior calendar month.

    Returns `{"this_month_total", "last_month_total", "delta", "pct_change"}`.
    Uses *like-for-like* windows: month-to-day-of-month for both months,
    so the comparison is fair early in the month (e.g. May 1–23 vs Apr 1–23
    rather than May 1–23 vs all of April). When the prior month has fewer
    days than today.day, the prior window is clipped to that month's last
    day. `pct_change` is None when `last_month_total` is 0 — the template
    renders that case as `—`.
    """
    this_start = date(today.year, today.month, 1)
    if today.month == 1:
        last_month_year, last_month_month = today.year - 1, 12
    else:
        last_month_year, last_month_month = today.year, today.month - 1
    last_start = date(last_month_year, last_month_month, 1)
    last_month_last_day = monthrange(last_month_year, last_month_month)[1]
    last_end = date(
        last_month_year, last_month_month, min(today.day, last_month_last_day)
    )

    db = get_db()
    try:
        this_total = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses "
            "WHERE user_id = ? AND date BETWEEN ? AND ?",
            (user_id, this_start.isoformat(), today.isoformat()),
        ).fetchone()["s"]
        last_total = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses "
            "WHERE user_id = ? AND date BETWEEN ? AND ?",
            (user_id, last_start.isoformat(), last_end.isoformat()),
        ).fetchone()["s"]
    finally:
        db.close()

    this_total = float(this_total)
    last_total = float(last_total)
    delta = this_total - last_total
    pct_change = (delta / last_total * 100) if last_total else None
    return {
        "this_month_total": this_total,
        "last_month_total": last_total,
        "delta": delta,
        "pct_change": pct_change,
    }


def get_highest_spending_month(user_id):
    """Return the single calendar month with the highest total for the user.

    `{"month": "YYYY-MM", "label": "March 2026", "amount": float}` or `None`.
    """
    db = get_db()
    try:
        row = db.execute(
            "SELECT strftime('%Y-%m', date) AS m, SUM(amount) AS s "
            "FROM expenses WHERE user_id = ? "
            "GROUP BY m ORDER BY s DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    finally:
        db.close()

    if row is None:
        return None
    month = row["m"]
    return {
        "month": month,
        "label": datetime.strptime(month, "%Y-%m").strftime("%B %Y"),
        "amount": float(row["s"]),
    }


def get_earliest_expense_date(user_id):
    """Return the user's earliest expense `date` as a `date`, or None."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT MIN(date) AS d FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        db.close()
    if row is None or row["d"] is None:
        return None
    return datetime.strptime(row["d"], "%Y-%m-%d").date()
