"""Тесты разбора аргументов /pause. Запуск: python -m tests.test_pause_args

Команда редкая и вызывается в неподходящий момент (болезнь, травма),
поэтому разбор нарочно терпимый: дата принимается в любой позиции.
"""

import os
from datetime import date

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("CHAT_ID", "-100")
os.environ.setdefault("DB_PATH", "/tmp/test-pause-never-written.db")

from handlers import parse_user_date, split_pause_args  # noqa: E402

TODAY = date(2026, 11, 5)
failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: получили {got!r}, ожидали {want!r}")


check("формат с точками", parse_user_date("04.11.2026"), date(2026, 11, 4))
check("без ведущего нуля", parse_user_date("4.11.2026"), date(2026, 11, 4))
check("короткий год", parse_user_date("04.11.26"), date(2026, 11, 4))
check("ISO тоже принимается", parse_user_date("2026-11-04"), date(2026, 11, 4))
check("не дата", parse_user_date("связки"), None)

check("пусто — сегодня, без причины",
      split_pause_args([], TODAY), (TODAY, None, None))
check("только причина",
      split_pause_args(["порваны", "связки"], TODAY), (TODAY, "порваны связки", None))
check("дата сразу после числа дней",
      split_pause_args(["04.11.2026", "связки"], TODAY), (date(2026, 11, 4), "связки", None))
check("дата последним словом",
      split_pause_args(["связки", "04.11.2026"], TODAY), (date(2026, 11, 4), "связки", None))
check("дата в середине",
      split_pause_args(["порваны", "04.11.2026", "связки"], TODAY),
      (date(2026, 11, 4), "порваны связки", None))
check("только дата, без причины",
      split_pause_args(["04.11.2026"], TODAY), (date(2026, 11, 4), None, None))
check("вторая дата остаётся текстом",
      split_pause_args(["04.11.2026", "до", "18.11.2026"], TODAY),
      (date(2026, 11, 4), "до 18.11.2026", None))

# Главное: огрызок даты не утекает в причину, а возвращается как ошибка.
check("неполная дата — ошибка, а не причина",
      split_pause_args(["04.11", "связки"], TODAY), (TODAY, None, "04.11"))
check("несуществующая дата — ошибка",
      split_pause_args(["32.11.2026"], TODAY), (TODAY, None, "32.11.2026"))
check("слово с цифрами не считается датой",
      split_pause_args(["ковид19"], TODAY), (TODAY, "ковид19", None))

if failures:
    print("ПРОВАЛЕНО:")
    for f in failures:
        print("  •", f)
    raise SystemExit(1)
print("✓ все проверки разбора /pause пройдены")
