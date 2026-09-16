"""Render what the daily summary would look like, without sending anything.

Usage:
    python preview_summary.py              # preview yesterday's summary (the one the 09:00 job would post today)
    python preview_summary.py 2026-04-15   # preview a specific day
"""

import random
import sys
from datetime import date, timedelta

from config import current_local_day
from quotes import MOTIVATIONAL
import streak_rules
from scheduler import build_summary_text


def _sample_quote() -> str:
    """Pick a quote *without* marking it used.

    random_motivational() persists the pick to the `used_quotes` table, which
    would burn quotes out of the live rotation just for a dry-run preview.
    """
    return random.choice(MOTIVATIONAL)


def main() -> None:
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        day = current_local_day() - timedelta(days=1)

    print("—" * 40)
    print("09:00 — сводка + цитата:")
    print("—" * 40)
    # persist=False: превью ничего не меняет в БД
    states = streak_rules.recompute_all(day, persist=False)
    print(build_summary_text(day, states))
    print()
    print(f"💬 {_sample_quote()}")
    print("—" * 40)
    print("15:00 — цитата:")
    print("—" * 40)
    print(f"💬 {_sample_quote()}")
    print("—" * 40)
    print("21:00 — цитата:")
    print("—" * 40)
    print(f"💬 {_sample_quote()}")
    print("—" * 40)


if __name__ == "__main__":
    main()
