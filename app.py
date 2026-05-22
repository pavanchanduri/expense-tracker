import math
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash

from database.db import get_db, init_db, seed_db, create_user, get_user_by_email
from database.queries import (
    CATEGORIES,
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
    insert_expense,
    get_expense_by_id,
    update_expense,
)

MAX_AMOUNT = 10_000_000  # ₹1 crore; reject larger inputs server-side

app = Flask(__name__)

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY environment variable is required in production.")
    _secret_key = secrets.token_hex(32)
app.secret_key = _secret_key

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Date filter helpers (Step 6)                                        #
# ------------------------------------------------------------------ #


def _validate_iso_date(value):
    """Return value if it is a well-formed YYYY-MM-DD string, else None."""
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        return None


def _resolve_presets(today):
    """Build the bounded preset → (date_from, date_to) mapping for `today`.

    All Time has no params and is therefore not included here.
    """
    first_of_month = today.replace(day=1)
    return {
        "this_month": (first_of_month.isoformat(), today.isoformat()),
        "last_3_months": ((today - timedelta(days=90)).isoformat(), today.isoformat()),
        "last_6_months": ((today - timedelta(days=180)).isoformat(), today.isoformat()),
    }


def _validate_expense_form(amount_raw, category, date_raw):
    """Validate add/edit expense form fields. Return (amount_float, error_msg).

    `error_msg` is None on success; on failure `amount_float` is None.
    """
    try:
        amount = float(amount_raw)
    except ValueError:
        return None, "Amount must be a number greater than 0."
    if not math.isfinite(amount) or amount <= 0:
        return None, "Amount must be a number greater than 0."
    if amount > MAX_AMOUNT:
        return None, "Amount cannot exceed ₹1,00,00,000."
    if category not in CATEGORIES:
        return None, "Please choose a valid category."
    if _validate_iso_date(date_raw) is None:
        return None, "Please enter a valid date (YYYY-MM-DD)."
    return amount, None


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #


@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name or not email or not password or not confirm_password:
        return render_template(
            "register.html", error="All fields are required.", name=name, email=email
        )

    if password != confirm_password:
        return render_template(
            "register.html", error="Passwords do not match.", name=name, email=email
        )

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        return render_template(
            "register.html", error="Email already registered.", name=name, email=email
        )

    flash("Account created successfully! Please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template(
            "login.html", error="All fields are required.", email=email
        )

    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html", error="Invalid email or password.", email=email
        )

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("landing"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    date_from = _validate_iso_date(request.args.get("date_from", "").strip())
    date_to = _validate_iso_date(request.args.get("date_to", "").strip())

    if (date_from is None) != (date_to is None):  # only one of the pair provided
        date_from = date_to = None
    elif date_from and date_to and date_from > date_to:
        date_from = date_to = None
        flash("Start date must be before end date.", "error")

    presets = _resolve_presets(date.today())
    if date_from and date_to:
        active_preset = next(
            (key for key, bounds in presets.items() if bounds == (date_from, date_to)),
            "custom",
        )
    else:
        active_preset = "all"

    preset_labels = {
        "all": "all time",
        "this_month": "this month",
        "last_3_months": "last 3 months",
        "last_6_months": "last 6 months",
    }
    filter_label = preset_labels.get(active_preset) or f"{date_from} – {date_to}"

    user = get_user_by_id(session["user_id"])
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    stats = get_summary_stats(session["user_id"], date_from=date_from, date_to=date_to)
    transactions = get_recent_transactions(
        session["user_id"], date_from=date_from, date_to=date_to
    )
    categories = get_category_breakdown(
        session["user_id"], date_from=date_from, date_to=date_to
    )

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        presets=presets,
        active_preset=active_preset,
        filter_label=filter_label,
        date_from=date_from or "",
        date_to=date_to or "",
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date_raw = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    def _form_with_error(msg):
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            today=date.today().isoformat(),
            error=msg,
            amount=amount_raw,
            category=category,
            date=date_raw,
            description=description,
        )

    amount, error = _validate_expense_form(amount_raw, category, date_raw)
    if error:
        return _form_with_error(error)

    insert_expense(session["user_id"], amount, category, date_raw, description)
    flash("Expense added.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
def edit_expense(expense_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(expense_id, session["user_id"])
    if expense is None:
        flash("Expense not found.", "error")
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            amount=expense["amount"],
            category=expense["category"],
            date=expense["date"],
            description=expense["description"] or "",
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date_raw = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    def _form_with_error(msg):
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            error=msg,
            amount=amount_raw,
            category=category,
            date=date_raw,
            description=description,
        )

    amount, error = _validate_expense_form(amount_raw, category, date_raw)
    if error:
        return _form_with_error(error)

    rows_affected = update_expense(
        expense_id, session["user_id"], amount, category, date_raw, description
    )
    if rows_affected == 0:
        flash("Expense not found.", "error")
        return redirect(url_for("profile"))
    flash("Expense updated.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/delete")
def delete_expense(expense_id):
    return "Delete expense — coming in Step 9"


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug, port=5001)
