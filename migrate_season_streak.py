"""Migration: switch streaks to the monthly-skip rule starting at SEASON_START.

1. Backs up the SQLite file.
2. Ensures the `skip_used_month` column exists on `streaks`.
3. Resets per-user state for the season (preserving best_streak as a floor):
       - current_streak  := 0
       - last_passed_date := NULL
       - skip_used_month := NULL
4. Runs recount_streaks.recount() which walks day-by-day from SEASON_START
   to yesterday applying the new rule.

Idempotent: safe to re-run (the recount overwrites state from video_notes).

Usage on server:
    systemctl --user stop pushups-bot
    .venv/bin/python migrate_season_streak.py
    systemctl --user start pushups-bot
"""

import shutil
from datetime import datetime
from pathlib import Path

import db
from config import DB_PATH, SEASON_START
import recount_streaks


def main() -> None:
    src = Path(DB_PATH)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.parent / f"{src.name}.bak.{ts}"
    shutil.copy2(src, dst)
    print(f"backup → {dst}")

    db.init_db()  # adds skip_used_month column if missing

    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) AS c FROM streaks").fetchone()["c"]
        conn.execute(
            "UPDATE streaks SET current_streak = 0,"
            " last_passed_date = NULL,"
            " skip_used_month = NULL"
        )
        print(f"reset state for {before} streak rows (best_streak preserved)")

    print(f"\n[recount] season start = {SEASON_START}")
    recount_streaks.recount()
    print("\nDONE")


if __name__ == "__main__":
    main()
