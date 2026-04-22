"""Recompute streaks from scratch based on existing video_notes.

Walks every date from BACKFILL_SINCE up to *yesterday* (the daily scheduler
will handle today at 00:00). For each user computes:
- current_streak: consecutive days with >= DAILY_GOAL up to the latest counted day
- best_streak:    longest run of consecutive qualifying days in the period
- last_passed_date: most recent day the user hit the goal

Run any time the video_notes table changes outside of the live bot
(e.g. after a backfill).

Usage:
    python recount_streaks.py
"""

from datetime import date, datetime, timedelta

import db
from config import BACKFILL_SINCE, DAILY_GOAL, current_local_day


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def recount() -> None:
    db.init_db()

    start = datetime.fromisoformat(BACKFILL_SINCE).date()
    yesterday = current_local_day() - timedelta(days=1)
    if yesterday < start:
        print(f"[recount] nothing to do (yesterday {yesterday} < start {start})")
        return

    users = db.all_users()
    print(f"[recount] {len(users)} users, range {start} .. {yesterday}")

    with db.connect() as conn:
        for u in users:
            user_id = u["user_id"]
            current = 0
            best = 0
            last_passed: date | None = None

            for day in _daterange(start, yesterday):
                count = conn.execute(
                    "SELECT COUNT(*) AS c FROM video_notes"
                    " WHERE user_id = ? AND local_date = ?",
                    (user_id, day.isoformat()),
                ).fetchone()["c"]

                if count >= DAILY_GOAL:
                    current += 1
                    best = max(best, current)
                    last_passed = day
                else:
                    current = 0

            conn.execute(
                """
                INSERT INTO streaks (user_id, current_streak, best_streak, last_passed_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_streak = excluded.current_streak,
                    best_streak = excluded.best_streak,
                    last_passed_date = excluded.last_passed_date
                """,
                (
                    user_id,
                    current,
                    best,
                    last_passed.isoformat() if last_passed else None,
                ),
            )

            name = u["username"] or u["first_name"] or f"id{user_id}"
            last_str = last_passed.isoformat() if last_passed else "—"
            print(
                f"  {name}: current={current} best={best} last_passed={last_str}"
            )

    print("[recount] done")


if __name__ == "__main__":
    recount()
