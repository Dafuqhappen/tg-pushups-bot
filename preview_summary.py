"""Render what the daily summary would look like, without sending anything.

Usage:
    python preview_summary.py              # preview yesterday's summary (the one the 09:00 job would post today)
    python preview_summary.py 2026-04-15   # preview a specific day
"""

import sys
from datetime import date, timedelta

from config import current_local_day
from quotes import random_bros, random_motivational
from scheduler import build_summary_text


def main() -> None:
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        day = current_local_day() - timedelta(days=1)

    print("—" * 40)
    print("09:00 — сводка + мотивационная цитата:")
    print("—" * 40)
    print(build_summary_text(day))
    print()
    print(f"💬 {random_motivational()}")
    print("—" * 40)
    print("15:00 — bros-цитата:")
    print("—" * 40)
    print(f"💬 {random_bros()}")
    print("—" * 40)
    print("21:00 — мотивационная цитата:")
    print("—" * 40)
    print(f"💬 {random_motivational()}")
    print("—" * 40)


if __name__ == "__main__":
    main()
