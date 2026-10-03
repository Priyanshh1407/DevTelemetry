import sqlite3
import os
from contextlib import contextmanager

# Resolve paths from this file's location so the app works from any working directory.
# DB_PATH can be overridden (e.g. tests point it at a temporary database).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "data", "schema.sql")


def get_db_path():
    """Returns the active database path, read at call time so it can be overridden."""
    return os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "data", "usage.db"))


def get_db_connection():
    """
    Creates and returns a database connection. The caller must close it;
    prefer db_session(), which does that.
    Sets row_factory so we can access columns by name (like a dictionary).
    """
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    """Connection for one unit of work: commits on success, rolls back on error, always closes.

    (sqlite3's own `with conn:` only commits/rolls back. It never closes the connection,
    so every request that used it leaked a file handle until garbage collection.)
    """
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """
    Initializes the database by running the schema.sql file.
    Only creates tables if they don't already exist.
    """
    # Ensure the data directory exists
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with open(SCHEMA_PATH, 'r') as f:
        schema_script = f.read()
    with db_session() as conn:
        # executescript allows us to run multiple SQL commands at once
        conn.executescript(schema_script)

    print(f"Database initialized successfully at {db_path}")


if __name__ == "__main__":
    # Allows you to run this file directly to test the setup
    init_db()
