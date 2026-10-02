import sqlite3
import os
import datetime

# Resolve paths from this file's location so the app works from any working directory.
# DB_PATH can be overridden (e.g. tests point it at a temporary database).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "data", "schema.sql")


def get_db_path():
    """Returns the active database path, read at call time so it can be overridden."""
    return os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "data", "usage.db"))


def get_db_connection():
    """
    Creates and returns a database connection.
    Sets row_factory so we can access columns by name (like a dictionary).
    """
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes the database by running the schema.sql file.
    Only creates tables if they don't already exist.
    """
    # Ensure the data directory exists
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    with get_db_connection() as conn:
        with open(SCHEMA_PATH, 'r') as f:
            schema_script = f.read()
        
        # executescript allows us to run multiple SQL commands at once
        conn.executescript(schema_script)
        conn.commit()
        
    print(f"Database initialized successfully at {db_path}")

def get_daily_records(date_str=None):
    """
    Fetches all engineer records for a specific date.
    Defaults to yesterday's date if none is provided.
    """
    if not date_str:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    try:
        # Utilizing your existing connection helper
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # CRITICAL: Verify that 'usage_data' matches the actual table name in your schema.sql
            cursor.execute("SELECT * FROM usage_data WHERE date = ?", (date_str,))
            rows = cursor.fetchall()
            
            # Convert sqlite3.Row objects to standard Python dicts for the Jinja template
            return [dict(row) for row in rows]
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []

if __name__ == "__main__":
    # Allows you to run this file directly to test the setup
    init_db()
    
    # Optional test to print yesterday's data directly to the terminal
    # records = get_daily_records()
    # print(f"Found {len(records)} records for yesterday.")