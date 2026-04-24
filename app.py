from flask import Flask, render_template, request, redirect, url_for, flash, session
from database.db import get_db, init_db, seed_db, create_user, get_user_by_email
from werkzeug.security import check_password_hash
import sqlite3

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"

with app.app_context():
    init_db()
    seed_db()


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
        return render_template("register.html", error="All fields are required.", name=name, email=email)

    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match.", name=name, email=email)

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        return render_template("register.html", error="Email already registered.", name=name, email=email)

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
        return render_template("login.html", error="All fields are required.", email=email)

    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.", email=email)

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

    user = {
        "name": session.get("user_name", "Nitish Singh"),
        "email": "nitish@spendly.com",
        "member_since": "January 2025",
    }

    stats = {
        "total_spent": 18240,
        "transaction_count": 34,
        "top_category": "Food",
    }

    transactions = [
        {"date": "2025-04-15", "description": "Dinner with friends",  "category": "Food",          "amount": 450.00},
        {"date": "2025-04-13", "description": "Stationery",           "category": "Other",         "amount": 350.00},
        {"date": "2025-04-11", "description": "New shoes",            "category": "Shopping",      "amount": 2500.00},
        {"date": "2025-04-09", "description": "Movie tickets",        "category": "Entertainment", "amount": 500.00},
        {"date": "2025-04-07", "description": "Pharmacy",             "category": "Health",        "amount": 800.00},
        {"date": "2025-04-05", "description": "Electricity bill",     "category": "Bills",         "amount": 1200.00},
        {"date": "2025-04-03", "description": "Auto to office",       "category": "Transport",     "amount": 150.00},
        {"date": "2025-04-01", "description": "Lunch at cafe",        "category": "Food",          "amount": 250.00},
    ]

    categories = [
        {"name": "Shopping",      "total": 2500, "percentage": 100},
        {"name": "Bills",         "total": 1200, "percentage": 48},
        {"name": "Health",        "total": 800,  "percentage": 32},
        {"name": "Food",          "total": 700,  "percentage": 28},
        {"name": "Entertainment", "total": 500,  "percentage": 20},
        {"name": "Other",         "total": 350,  "percentage": 14},
        {"name": "Transport",     "total": 150,  "percentage": 6},
    ]

    return render_template("profile.html",
                           user=user,
                           stats=stats,
                           transactions=transactions,
                           categories=categories)


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


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
