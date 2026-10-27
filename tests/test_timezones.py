"""Тесты разрешения персональных поясов. Запуск: python -m tests.test_timezones

Проверяется главное свойство: пояс, заданный с какой-то даты, не должен
действовать на более ранние кружки. Иначе переезд переписывает прошлое —
на этом мы уже один раз едва не потеряли стодневный стрик.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("CHAT_ID", "-100")
os.environ.setdefault("DB_PATH", "/tmp/test-tz-never-written.db")

import timezones  # noqa: E402
from config import TIMEZONE  # noqa: E402

MSK = ZoneInfo("Europe/Moscow")
ALM = ZoneInfo("Asia/Almaty")
VN = ZoneInfo("Asia/Ho_Chi_Minh")
UID = 1

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: получили {got}, ожидали {want}")


# Подменяем кэш напрямую — БД для проверки логики не нужна.
timezones._cache = {
    UID: [(date(2026, 10, 6), ALM), (date(2026, 10, 12), VN)],
}


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=MSK)


check("до первого периода — общий пояс", timezones.timezone_for(UID, at(5, 12)), TIMEZONE)
check("в день начала период уже действует", timezones.timezone_for(UID, at(6, 12)), ALM)
check("середина первого периода", timezones.timezone_for(UID, at(9, 12)), ALM)
check("последний день первого периода", timezones.timezone_for(UID, at(11, 23)), ALM)
check("в день переезда — новый пояс", timezones.timezone_for(UID, at(12, 12)), VN)
check("после переезда", timezones.timezone_for(UID, at(20, 12)), VN)
check("без момента — самый свежий период", timezones.timezone_for(UID), VN)
check("у кого периодов нет — общий пояс", timezones.timezone_for(999, at(20, 12)), TIMEZONE)
check("аноним — общий пояс", timezones.timezone_for(None, at(20, 12)), TIMEZONE)

# Границу считаем по общему поясу, иначе точка отсчёта зависела бы от того,
# какой пояс мы как раз и выбираем.
check("граница по МСК: 23:00 11-го ещё Алматы", timezones.timezone_for(UID, at(11, 23)), ALM)
check("граница по МСК: 00:30 12-го уже Вьетнам", timezones.timezone_for(UID, at(12, 0, 30)), VN)

# Принимается и город, и IANA-имя; мусор отбрасывается.
check("город → IANA", timezones.resolve_name("Нячанг"), "Asia/Ho_Chi_Minh")
check("регистр не важен", timezones.resolve_name("МОСКВА"), "Europe/Moscow")
check("пробелы по краям", timezones.resolve_name("  алматы "), "Asia/Almaty")
check("IANA напрямую", timezones.resolve_name("Asia/Bangkok"), "Asia/Bangkok")
check("мусор", timezones.resolve_name("где-то там"), None)
check("пустая строка", timezones.resolve_name("   "), None)

timezones._cache = None

if failures:
    print("ПРОВАЛЕНО:")
    for f in failures:
        print("  •", f)
    raise SystemExit(1)
print("✓ все проверки поясов пройдены")
