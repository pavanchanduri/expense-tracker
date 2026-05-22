import math
import os
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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

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

    try:
        amount = float(amount_raw)
    except ValueError:
        return _form_with_error("Amount must be a number greater than 0.")
    if not math.isfinite(amount) or amount <= 0:
        return _form_with_error("Amount must be a number greater than 0.")
    if category not in CATEGORIES:
        return _form_with_error("Please choose a valid category.")
    if _validate_iso_date(date_raw) is None:
        return _form_with_error("Please enter a valid date (YYYY-MM-DD).")

    insert_expense(session["user_id"], amount, category, date_raw, description)
    flash("Expense added.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(id, session["user_id"])
    if expense is None:
        flash("Expense not found.", "error")
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
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

    try:
        amount = float(amount_raw)
    except ValueError:
        return _form_with_error("Amount must be a number greater than 0.")
    if not math.isfinite(amount) or amount <= 0:
        return _form_with_error("Amount must be a number greater than 0.")
    if category not in CATEGORIES:
        return _form_with_error("Please choose a valid category.")
    if _validate_iso_date(date_raw) is None:
        return _form_with_error("Please enter a valid date (YYYY-MM-DD).")

    update_expense(id, session["user_id"], amount, category, date_raw, description)
    flash("Expense updated.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
