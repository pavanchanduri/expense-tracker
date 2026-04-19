import sqlite3
import os
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "expense_tracker.db")


def get_db():
    """Return a SQLite connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_user(name, email, password):
    """Hash password and insert a new user. Returns the new user id.
    Raises sqlite3.IntegrityError if email is already taken."""
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
        return db.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        db.close()


def init_db():
    """Create tables if they don't already exist."""
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    db.close()


def seed_db():
    """Insert demo user and sample expenses (only if the users table is empty)."""
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        db.close()
        return

    # Demo user
    db.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123", method="pbkdf2:sha256")),
    )
    user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 8 sample expenses spread across the current month
    today = date.today()
    first = today.replace(day=1)
    expenses = [
        (user_id, 250.00,  "Food",          (first + timedelta(days=1)).isoformat(),  "Lunch at cafe"),
        (user_id, 150.00,  "Transport",     (first + timedelta(days=3)).isoformat(),  "Auto to office"),
        (user_id, 1200.00, "Bills",         (first + timedelta(days=5)).isoformat(),  "Electricity bill"),
        (user_id, 800.00,  "Health",        (first + timedelta(days=7)).isoformat(),  "Pharmacy"),
        (user_id, 500.00,  "Entertainment", (first + timedelta(days=9)).isoformat(),  "Movie tickets"),
        (user_id, 2500.00, "Shopping",      (first + timedelta(days=11)).isoformat(), "New shoes"),
        (user_id, 350.00,  "Other",         (first + timedelta(days=13)).isoformat(), "Stationery"),
        (user_id, 450.00,  "Food",          (first + timedelta(days=15)).isoformat(), "Dinner with friends"),
    ]
    db.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    db.commit()
    db.close()
