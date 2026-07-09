"""Database connection and initialization module."""
import sqlite3
from pathlib import Path
from typing import Optional

DATABASE_PATH = Path(__file__).parent.parent.parent / "data" / "my_agent.db"

def get_connection() -> sqlite3.Connection:
    """Get a database connection.
    
    Returns:
        sqlite3.Connection: Database connection object
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_database() -> None:
    """Initialize the database with schema."""
    schema_path = Path(__file__).parent / "schema.sql"
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print("Database initialized successfully!")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()