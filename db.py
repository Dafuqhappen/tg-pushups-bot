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
    last_passed_date  TEXT,
    skip_used_month   TEXT
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
        # In-place schema migration: add skip_used_month if старая БД
        # без этого столбца. ALTER TABLE на SQLite — мгновенный для NULL-ового
        # дополнения, без блокировок.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(streaks)").fetchall()}
        if "skip_used_month" not in cols:
            conn.execute("ALTER TABLE streaks ADD COLUMN skip_used_month TEXT")


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
    """Advance streak under the monthly-skip rule.

    - Pass day: current += 1 (или = 1, если стрик был разорван либо это
      первый день). Если между last_passed и сегодня ровно один пропущенный
      день, и этот пропуск пришёлся на месяц, для которого был помечен
      `skip_used_month`, — стрик считается «мостом», current += 1.
    - Miss day, skip ещё не использовался в этом месяце: помечаем месяц как
      использованный, current и last_passed не трогаем. Стрик «прощает» один
      пропуск.
    - Miss day, skip уже использован в этом месяце: current = 0. Бонус не
      возобновляется до следующего месяца.

    best_streak — only growing, никогда не уменьшается (all-time рекорд).
    """
    from datetime import timedelta
    month_key = day.strftime("%Y-%m")

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM streaks WHERE user_id = ?", (user_id,)
        ).fetchone()

        if row is None:
            if passed:
                conn.execute(
                    "INSERT INTO streaks (user_id, current_streak, best_streak,"
                    " last_passed_date, skip_used_month)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (user_id, 1, 1, day.isoformat(), None),
                )
            else:
                # Первая запись для юзера + miss day. Стрика нет, но месяц
                # помечаем как «было пусто» — иначе следующий пропуск был бы
                # «первым в месяце» и сжёг бы второй бонус.
                conn.execute(
                    "INSERT INTO streaks (user_id, current_streak, best_streak,"
                    " last_passed_date, skip_used_month)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (user_id, 0, 0, None, month_key),
                )
            return

        current = row["current_streak"]
        best = row["best_streak"]
        last_passed = (
            date.fromisoformat(row["last_passed_date"])
            if row["last_passed_date"] else None
        )
        skip_used_month = row["skip_used_month"]  # may be None

        if passed:
            if current == 0 or last_passed is None:
                current = 1
            elif (day - last_passed).days == 1:
                current += 1
            elif (day - last_passed).days == 2:
                # Возможный «мост» через прощённый пропуск
                gap_day = day - timedelta(days=1)
                if skip_used_month == gap_day.strftime("%Y-%m"):
                    current += 1
                else:
                    current = 1
            elif (day - last_passed).days == 0:
                # Повторный pass за тот же день — ничего не меняем
                pass
            else:
                # Больший gap или нет валидного skip → новая серия
                current = 1
            best = max(best, current)
            last_passed = day
        else:
            if skip_used_month != month_key:
                # Первый пропуск в этом месяце — прощаем, стрик жив
                skip_used_month = month_key
            else:
                # Второй пропуск в этом месяце — стрик сгорает.
                # skip_used_month оставляем как есть — он привязан к месяцу,
                # а не к стрику, и не должен сбрасываться до новой месячной
                # границы.
                current = 0

        conn.execute(
            "UPDATE streaks SET current_streak = ?, best_streak = ?,"
            " last_passed_date = ?, skip_used_month = ?"
            " WHERE user_id = ?",
            (
                current,
                best,
                last_passed.isoformat() if last_passed else None,
                skip_used_month,
                user_id,
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
