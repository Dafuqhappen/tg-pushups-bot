"""Покажи дневные счётчики кружков юзера за месяц.

Usage:
    .venv/bin/python june_counts.py <user_id>                # все дни июня
    .venv/bin/python june_counts.py <user_id> 2026-05        # любой месяц
"""

import sqlite3
import sys
from datetime import date, timedelta

from config import DB_PATH, DAILY_GOAL

if len(sys.argv) < 2:
    raise SystemExit("usage: june_counts.py <user_id> [YYYY-MM]")

user_id = int(sys.argv[1])
yyyymm = sys.argv[2] if len(sys.argv) > 2 else "2026-06"
year, month = map(int, yyyymm.split("-"))

start = date(year, month, 1)
if month == 12:
    end = date(year + 1, 1, 1) - timedelta(days=1)
else:
    end = date(year, month + 1, 1) - timedelta(days=1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# фактические счётчики из БД
counts = {
    r["local_date"]: r["c"]
    for r in conn.execute(
        """
        SELECT local_date, COUNT(*) AS c
        FROM video_notes
        WHERE user_id = ? AND local_date BETWEEN ? AND ?
        GROUP BY local_date
        """,
        (user_id, start.isoformat(), end.isoformat()),
    )
}

print(f"User {user_id} — {yyyymm} daily counts (goal: {DAILY_GOAL}):")
print(f"{'local_date':<12} {'count':<6} status")
print("-" * 40)

passed = miss = 0
day = start
while day <= end:
    iso = day.isoformat()
    c = counts.get(iso, 0)
    status = "✅ pass" if c >= DAILY_GOAL else ("❌ miss" if c > 0 else "⚪ zero")
    if c >= DAILY_GOAL:
        passed += 1
    elif c > 0:
        miss += 1
    print(f"{iso:<12} {c:<6} {status}")
    day += timedelta(days=1)

print("-" * 40)
print(f"всего pass-дней: {passed} / {(end - start).days + 1}")
print(f"miss (с кружками < {DAILY_GOAL}): {miss}")
