import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    first_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_notes (
    message_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    sent_at    TEXT    NOT NULL,
    local_date TEXT    NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_notes_user_date
    ON video_notes(user_id, local_date);

CREATE TABLE IF NOT EXISTS streaks (
    user_id           INTEGER PRIMARY KEY,
    current_streak    INTEGER NOT NULL DEFAULT 0,
    best_streak       INTEGER NOT NULL DEFAULT 0,
    last_passed_date  TEXT
);

CREATE TABLE IF NOT EXISTS used_quotes (
    bucket TEXT NOT NULL,
    quote  TEXT NOT NULL,
    PRIMARY KEY (bucket, quote)
);
"""


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    *,
    update_first_name: bool = True,
) -> None:
    """Insert or refresh a user row.

    With `update_first_name=False`, leave first_name untouched for existing
    users — used by the Telethon backfill, where `first_name` is the caller's
    contact label, not the user's real profile name.
    """
    with connect() as conn:
        if update_first_name:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, first_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (user_id, username, first_name, datetime.utcnow().isoformat()),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, first_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username
                """,
                (user_id, username, first_name, datetime.utcnow().isoformat()),
            )


def record_video_note(
    message_id: int, user_id: int, sent_at: datetime, local_date: date
) -> bool:
    """Returns True if inserted, False if already existed."""
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO video_notes (message_id, user_id, sent_at, local_date)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, user_id, sent_at.isoformat(), local_date.isoformat()),
        )
        return cur.rowcount > 0


def count_for_day(user_id: int, day: date) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM video_notes WHERE user_id = ? AND local_date = ?",
            (user_id, day.isoformat()),
        ).fetchone()
        return row["c"]


def counts_for_day(day: date) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT u.user_id, u.username, u.first_name, COUNT(v.message_id) AS count
            FROM users u
            LEFT JOIN video_notes v
                ON v.user_id = u.user_id AND v.local_date = ?
            GROUP BY u.user_id
            ORDER BY count DESC
            """,
            (day.isoformat(),),
        ).fetchall()


def total_for_user(user_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM video_notes WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["c"]


def get_streak(user_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM streaks WHERE user_id = ?", (user_id,)
        ).fetchone()


def update_streak(user_id: int, day: date, passed: bool) -> None:
    """Advance streak if passed and day is consecutive; reset if not."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM streaks WHERE user_id = ?", (user_id,)
        ).fetchone()

        if row is None:
            current = 1 if passed else 0
            best = current
            last = day.isoformat() if passed else None
            conn.execute(
                "INSERT INTO streaks (user_id, current_streak, best_streak, last_passed_date)"
                " VALUES (?, ?, ?, ?)",
                (user_id, current, best, last),
            )
            return

        current = row["current_streak"]
        best = row["best_streak"]
        last = date.fromisoformat(row["last_passed_date"]) if row["last_passed_date"] else None

        if passed:
            if last is None or (day - last).days > 1:
                current = 1
            elif (day - last).days == 1:
                current += 1
            # (day - last).days == 0 → already counted, keep current
            best = max(best, current)
            last = day
        else:
            current = 0

        conn.execute(
            "UPDATE streaks SET current_streak = ?, best_streak = ?, last_passed_date = ?"
            " WHERE user_id = ?",
            (current, best, last.isoformat() if last else None, user_id),
        )


def all_users() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM users").fetchall()


def get_used_quotes(bucket: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT quote FROM used_quotes WHERE bucket = ?", (bucket,)
        ).fetchall()
        return {r["quote"] for r in rows}


def mark_quote_used(bucket: str, quote: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO used_quotes (bucket, quote) VALUES (?, ?)",
            (bucket, quote),
        )


def clear_used_quotes(bucket: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM used_quotes WHERE bucket = ?", (bucket,))
