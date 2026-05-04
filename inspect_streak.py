"""Quick read-only diagnostics for streak/cutoff debugging.

Usage:
    .venv/bin/python inspect_streak.py            # все юзеры
    .venv/bin/python inspect_streak.py 12345678   # фокус на одном user_id
"""

import sqlite3
import sys
from datetime import date, timedelta

from config import DB_PATH

DAYS = 7


def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 60)
    print("USERS")
    print("=" * 60)
    print(f"{'user_id':<12} {'first_name':<25} {'username':<25}")
    print("-" * 62)
    for r in conn.execute("SELECT user_id, first_name, username FROM users ORDER BY user_id"):
        marker = " ←" if target and r["user_id"] == target else ""
        print(f"{r['user_id']:<12} {(r['first_name'] or ''):<25} {(r['username'] or ''):<25}{marker}")

    print()
    print("=" * 60)
    print("STREAKS")
    print("=" * 60)
    q = "SELECT * FROM streaks"
    args = ()
    if target:
        q += " WHERE user_id = ?"
        args = (target,)
    print(f"{'user_id':<12} {'current':<8} {'best':<6} {'last_passed_date'}")
    print("-" * 50)
    for r in conn.execute(q, args):
        print(f"{r['user_id']:<12} {r['current_streak']:<8} {r['best_streak']:<6} {r['last_passed_date'] or '—'}")

    print()
    print("=" * 60)
    print(f"VIDEO NOTES — последние {DAYS} дней")
    print("=" * 60)

    cutoff = (date.today() - timedelta(days=DAYS)).isoformat()
    q = """
        SELECT message_id, user_id, sent_at, local_date
        FROM video_notes
        WHERE local_date >= ?
    """
    args = (cutoff,)
    if target:
        q += " AND user_id = ?"
        args = (cutoff, target)
    q += " ORDER BY sent_at"

    print(f"{'message_id':<12} {'user_id':<12} {'sent_at (UTC)':<22} {'local_date'}")
    print("-" * 60)
    for r in conn.execute(q, args):
        print(f"{r['message_id']:<12} {r['user_id']:<12} {r['sent_at']:<22} {r['local_date']}")

    print()
    print("=" * 60)
    print(f"COUNTS PER DAY — последние {DAYS} дней")
    print("=" * 60)

    q = """
        SELECT local_date, user_id, COUNT(*) AS c
        FROM video_notes
        WHERE local_date >= ?
    """
    args = (cutoff,)
    if target:
        q += " AND user_id = ?"
        args = (cutoff, target)
    q += " GROUP BY local_date, user_id ORDER BY local_date, user_id"

    print(f"{'local_date':<12} {'user_id':<12} {'count'}")
    print("-" * 36)
    for r in conn.execute(q, args):
        marker = " ✓" if r["c"] >= 4 else ""
        print(f"{r['local_date']:<12} {r['user_id']:<12} {r['c']}{marker}")

    conn.close()


if __name__ == "__main__":
    main()
