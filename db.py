import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from config import DB_PATH, SEASON_START

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
    user_id              INTEGER PRIMARY KEY,
    current_streak       INTEGER NOT NULL DEFAULT 0,
    best_streak          INTEGER NOT NULL DEFAULT 0,
    last_passed_date     TEXT,
    skip_used_month      TEXT,
    activity_streak      INTEGER NOT NULL DEFAULT 0,
    best_activity_streak INTEGER NOT NULL DEFAULT 0,
    last_active_date     TEXT,
    freeze_banked        INTEGER NOT NULL DEFAULT 0
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
        # In-place миграция схемы для БД, созданных ранними версиями.
        # ALTER TABLE ... ADD COLUMN на SQLite мгновенный и не блокирует.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(streaks)").fetchall()}
        for name, decl in (
            ("skip_used_month", "TEXT"),
            ("activity_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("best_activity_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("last_active_date", "TEXT"),
            ("freeze_banked", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE streaks ADD COLUMN {name} {decl}")


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


def counts_by_day(user_id: int) -> dict[date, int]:
    """Подневные счётчики одного участника за текущий сезон."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT local_date, COUNT(*) AS c FROM video_notes"
            " WHERE user_id = ? AND local_date >= ?"
            " GROUP BY local_date",
            (user_id, SEASON_START.isoformat()),
        ).fetchall()
    return {date.fromisoformat(r["local_date"]): r["c"] for r in rows}


def counts_by_day_all() -> dict[int, dict[date, int]]:
    """То же для всех сразу — один запрос вместо запроса на участника."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT user_id, local_date, COUNT(*) AS c FROM video_notes"
            " WHERE local_date >= ?"
            " GROUP BY user_id, local_date",
            (SEASON_START.isoformat(),),
        ).fetchall()
    out: dict[int, dict[date, int]] = {}
    for r in rows:
        out.setdefault(r["user_id"], {})[date.fromisoformat(r["local_date"])] = r["c"]
    return out


def save_state(user_id: int, st) -> None:
    """Сохранить посчитанное состояние. `st` — streak_rules.StreakState.

    Таблица здесь — кэш для быстрых чтений (/top, сводка). Источник правды —
    video_notes: состояние всегда можно пересобрать реплеем.
    """
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO streaks (user_id, current_streak, best_streak,
                                 last_passed_date, skip_used_month,
                                 activity_streak, best_activity_streak,
                                 last_active_date, freeze_banked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                current_streak = excluded.current_streak,
                best_streak = excluded.best_streak,
                last_passed_date = excluded.last_passed_date,
                skip_used_month = excluded.skip_used_month,
                activity_streak = excluded.activity_streak,
                best_activity_streak = excluded.best_activity_streak,
                last_active_date = excluded.last_active_date,
                freeze_banked = excluded.freeze_banked
            """,
            (
                user_id,
                st.current,
                st.best,
                st.last_passed.isoformat() if st.last_passed else None,
                st.amnesty_month,
                st.activity_current,
                st.activity_best,
                st.last_active.isoformat() if st.last_active else None,
                st.freeze_banked,
            ),
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
