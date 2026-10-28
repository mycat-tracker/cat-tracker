import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "cat.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            subtype TEXT,
            amount REAL,
            note TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user_date
            ON events(user_id, created_at);
        """)

# Изменили функцию: теперь она принимает готовую дату (строку)
def add_event(user_id: int, type_: str, subtype: str = None,
              amount: float = None, note: str = None, custom_date: str = None):
    event_date = custom_date if custom_date else datetime.now().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (user_id, type, subtype, amount, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, type_, subtype, amount, note, event_date)
        )

def month_stats(user_id: int, year: int, month: int):
    start = f"{year:04d}-{month:02d}-01T00:00:00"
    if month == 12:
        end = f"{year+1:04d}-01-01T00:00:00"
    else:
        end = f"{year:04d}-{month+1:02d}-01T00:00:00"
    with get_db() as conn:
        rows = conn.execute(
            "SELECT type, subtype, amount, created_at FROM events "
            "WHERE user_id=? AND created_at>=? AND created_at<? "
            "ORDER BY created_at",
            (user_id, start, end)
        ).fetchall()
    return rows

def get_last_events(user_id: int, limit: int = 5):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, type, subtype, amount, created_at FROM events "
            "WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return rows

def delete_event(event_id: int, user_id: int):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM events WHERE id=? AND user_id=?",
            (event_id, user_id)
        )
