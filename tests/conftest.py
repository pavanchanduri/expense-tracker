"""Shared pytest fixtures for the Spendly test suite.

Provides the three fixtures every test file used to redefine:

* ``app``     — the Flask app wired to a per-test temp-file SQLite DB.
* ``client``  — Flask test client built on that app.
* ``db_conn`` — a separate sqlite3.Connection to the same file so tests can
                inspect or seed rows without going through the Flask layer.

Per-test-file fixtures (``test_user_id``, ``auth_client``, ``other_user_id``,
seed helpers, etc.) intentionally stay local — they vary enough between
files that consolidating them would couple unrelated test modules.
"""

import sqlite3

import pytest

from app import app as flask_app
from database.db import init_db


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test.db")
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
