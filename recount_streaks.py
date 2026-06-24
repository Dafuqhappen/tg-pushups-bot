"""Recompute streaks from scratch based on existing video_notes.

Walks every date from SEASON_START up to *yesterday* (today is still
in-progress and gets evaluated by the daily scheduler at 09:00 МСК).

Streak rule (in effect since SEASON_START):
- Pass day (>= DAILY_GOAL kruzhki): current_streak += 1
- Miss day, first miss of the month: streak survives ("monthly skip")
- Miss day, second+ miss of the month: current_streak = 0

best_streak is preserved as an all-time floor — the recount can only
grow it, never shrink it.

Usage:
    python recount_streaks.py
"""

from datetime import date, timedelta

import db
from config import DAILY_GOAL, SEASON_START, current_local_day


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def recount() -> None:
    db.init_db()

    start = SEASON_START
    yesterday = current_local_day() - timedelta(days=1)
    if yesterday < start:
        print(f"[recount] nothing to do (yesterday {yesterday} < start {start})")
        return

    users = db.all_users()
    print(f"[recount] {len(users)} users, range {start} .. {yesterday}")

    with db.connect() as conn:
        for u in users:
            user_id = u["user_id"]

            # Preserve existing best_streak as an all-time floor.
            existing = conn.execute(
                "SELECT best_streak FROM streaks WHERE user_id = ?", (user_id,)
            ).fetchone()
            best = existing["best_streak"] if existing else 0

            current = 0
            last_passed: date | None = None
            skip_used_month: str | None = None

            for day in _daterange(start, yesterday):
                count = conn.execute(
                    "SELECT COUNT(*) AS c FROM video_notes"
                    " WHERE user_id = ? AND local_date = ?",
                    (user_id, day.isoformat()),
                ).fetchone()["c"]
                passed = count >= DAILY_GOAL
                month_key = day.strftime("%Y-%m")

                if passed:
                    if current == 0 or last_passed is None:
                        current = 1
                    elif (day - last_passed).days == 1:
                        current += 1
                    elif (day - last_passed).days == 2:
                        # Possible bridge via monthly skip
                        gap_day = day - timedelta(days=1)
                        if skip_used_month == gap_day.strftime("%Y-%m"):
                            current += 1
                        else:
                            current = 1
                    else:
                        current = 1
                    best = max(best, current)
                    last_passed = day
                else:
                    if skip_used_month != month_key:
                        skip_used_month = month_key
                    else:
                        current = 0

            conn.execute(
                """
                INSERT INTO streaks (user_id, current_streak, best_streak,
                                     last_passed_date, skip_used_month)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_streak = excluded.current_streak,
                    best_streak = excluded.best_streak,
                    last_passed_date = excluded.last_passed_date,
                    skip_used_month = excluded.skip_used_month
                """,
                (
                    user_id,
                    current,
                    best,
                    last_passed.isoformat() if last_passed else None,
                    skip_used_month,
                ),
            )

            name = u["username"] or u["first_name"] or f"id{user_id}"
            last_str = last_passed.isoformat() if last_passed else "—"
            skip_str = skip_used_month or "—"
            print(
                f"  {name}: current={current} best={best}"
                f" last_passed={last_str} skip_used={skip_str}"
            )

    print("[recount] done")


if __name__ == "__main__":
    recount()
