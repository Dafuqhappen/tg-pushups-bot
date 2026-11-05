"""Тесты разбора аргументов /pause. Запуск: python -m tests.test_pause_args

Команда редкая и вызывается в неподходящий момент (болезнь, травма),
поэтому разбор нарочно терпимый: дата принимается в любой позиции.
"""

import os
from datetime import date

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("CHAT_ID", "-100")
os.environ.setdefault("DB_PATH", "/tmp/test-pause-never-written.db")

from handlers import split_pause_args  # noqa: E402

TODAY = date(2026, 11, 5)
failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: получили {got!r}, ожидали {want!r}")


check("пусто — сегодня, без причины",
      split_pause_args([], TODAY), (TODAY, None))
check("только причина",
      split_pause_args(["порваны", "связки"], TODAY), (TODAY, "порваны связки"))
check("дата сразу после числа дней",
      split_pause_args(["2026-11-04", "связки"], TODAY), (date(2026, 11, 4), "связки"))
check("дата последним словом",
      split_pause_args(["связки", "2026-11-04"], TODAY), (date(2026, 11, 4), "связки"))
check("дата в середине",
      split_pause_args(["порваны", "2026-11-04", "связки"], TODAY),
      (date(2026, 11, 4), "порваны связки"))
check("только дата, без причины",
      split_pause_args(["2026-11-04"], TODAY), (date(2026, 11, 4), None))
check("вторая дата остаётся текстом",
      split_pause_args(["2026-11-04", "до", "2026-11-18"], TODAY),
      (date(2026, 11, 4), "до 2026-11-18"))
check("не-дата не съедается",
      split_pause_args(["04.11.2026", "связки"], TODAY), (TODAY, "04.11.2026 связки"))

if failures:
    print("ПРОВАЛЕНО:")
    for f in failures:
        print("  •", f)
    raise SystemExit(1)
print("✓ все проверки разбора /pause пройдены")
