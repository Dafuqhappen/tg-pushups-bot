"""One-off fix: Max sent two kruzhki on the morning of May 3 MSK (~08:07–08:13)
that fell under the 09:00 cutoff and got assigned to local_date=2026-05-02.
Result: May 2 logical day inflated to 6, May 3 logical day shrunk to 2,
streak broke even though calendar-wise May 3 had 4 kruzhki.

This script:
  1. Backs up the DB
  2. Re-assigns those two video_notes rows to local_date=2026-05-03
  3. Runs the standard recount to fix all streaks (Max's restored to its
     real run; everyone else stays correct since their data didn't change)

Read-only mode if you want to preview what would change:
    .venv/bin/python fix_max_streak.py --dry-run
"""

import argparse
import shutil
from datetime import date, datetime
from pathlib import Path

import db
from config import DB_PATH

USER_ID = 273430899  # Max
MESSAGE_IDS = (1979, 1980)
NEW_LOCAL_DATE = "2026-05-03"


def backup_db() -> Path:
    src = Path(DB_PATH)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.parent / f"{src.name}.bak.{ts}"
    shutil.copy2(src, dst)
    return dst


def show_state(label: str) -> None:
    print(f"\n--- {label} ---")
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT message_id, sent_at, local_date FROM video_notes"
            f" WHERE message_id IN ({','.join('?' * len(MESSAGE_IDS))}) AND user_id = ?",
            (*MESSAGE_IDS, USER_ID),
        ).fetchall()
        print("messages:")
        for r in rows:
            print(f"  msg={r['message_id']}  sent_at={r['sent_at']}  local_date={r['local_date']}")

        for d in ("2026-05-02", "2026-05-03"):
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM video_notes WHERE user_id = ? AND local_date = ?",
                (USER_ID, d),
            ).fetchone()["c"]
            print(f"  Max count on {d}: {cnt}")

        sr = conn.execute(
            "SELECT * FROM streaks WHERE user_id = ?", (USER_ID,)
        ).fetchone()
        if sr:
            print(
                f"  streak: current={sr['current_streak']} best={sr['best_streak']}"
                f" last_passed_date={sr['last_passed_date']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    show_state("BEFORE")

    if args.dry_run:
        print("\n(dry-run — ничего не меняем)")
        return

    bk = backup_db()
    print(f"\nbackup → {bk}")

    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE video_notes SET local_date = ?"
            f" WHERE message_id IN ({','.join('?' * len(MESSAGE_IDS))}) AND user_id = ?",
            (NEW_LOCAL_DATE, *MESSAGE_IDS, USER_ID),
        )
        print(f"\nUPDATE video_notes: {cur.rowcount} rows changed")

    print("\n[recount] пересчитываю стрики ...")
    # Lazy import — recount_streaks runs init_db on import-side via call,
    # plus prints its own progress lines.
    import recount_streaks
    recount_streaks.recount()

    show_state("AFTER")
    print("\nDONE")


if __name__ == "__main__":
    main()
