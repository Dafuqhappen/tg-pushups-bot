"""Персональные часовые пояса участников.

Пояс — свойство человека в моменте, а не аккаунта: люди переезжают.
Поэтому хранится не одно значение, а периоды «с такой-то даты — такой-то
пояс», и кружок июля считается по тому поясу, в котором человек тогда был.
Без этого смена пояса переписывала бы прошлое задним числом.

Telegram часовой пояс не отдаёт (в объекте User его просто нет), поэтому
участник сообщает его сам командой /timezone.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db
from config import TIMEZONE

# Город → IANA. Нужен, чтобы человек мог написать «Нячанг», а не
# «Asia/Ho_Chi_Minh». Список намеренно короткий — только то, что реально
# встречается в чате; всё остальное принимается как IANA-имя напрямую.
ALIASES: dict[str, str] = {
    "москва": "Europe/Moscow",
    "мск": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "спб": "Europe/Moscow",
    "алматы": "Asia/Almaty",
    "астана": "Asia/Almaty",
    "казахстан": "Asia/Almaty",
    "нячанг": "Asia/Ho_Chi_Minh",
    "вьетнам": "Asia/Ho_Chi_Minh",
    "ханой": "Asia/Ho_Chi_Minh",
    "сайгон": "Asia/Ho_Chi_Minh",
    "бангкок": "Asia/Bangkok",
    "таиланд": "Asia/Bangkok",
    "бали": "Asia/Makassar",
    "тбилиси": "Asia/Tbilisi",
    "грузия": "Asia/Tbilisi",
    "ереван": "Asia/Yerevan",
    "армения": "Asia/Yerevan",
    "стамбул": "Europe/Istanbul",
    "турция": "Europe/Istanbul",
    "белград": "Europe/Belgrade",
    "сербия": "Europe/Belgrade",
    "берлин": "Europe/Berlin",
    "дубай": "Asia/Dubai",
    "оаэ": "Asia/Dubai",
    "ташкент": "Asia/Tashkent",
    "бишкек": "Asia/Bishkek",
    "новосибирск": "Asia/Novosibirsk",
    "екатеринбург": "Asia/Yekaterinburg",
    "владивосток": "Asia/Vladivostok",
    "калининград": "Europe/Kaliningrad",
}

# Кэш периодов: {user_id: [(since, ZoneInfo), ...]} по возрастанию since.
_cache: dict[int, list[tuple[date, ZoneInfo]]] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def _periods() -> dict[int, list[tuple[date, ZoneInfo]]]:
    global _cache
    if _cache is not None:
        return _cache

    out: dict[int, list[tuple[date, ZoneInfo]]] = {}
    for r in db.timezone_rows():
        try:
            tz = ZoneInfo(r["tz"])
        except (ZoneInfoNotFoundError, ValueError):
            # Битая запись не должна ронять бота для всех остальных.
            continue
        out.setdefault(r["user_id"], []).append((date.fromisoformat(r["since"]), tz))
    for periods in out.values():
        periods.sort(key=lambda p: p[0])
    _cache = out
    return out


def resolve_name(text: str) -> str | None:
    """Превратить то, что написал человек, в IANA-имя. None — не узнали."""
    raw = text.strip()
    if not raw:
        return None
    alias = ALIASES.get(raw.lower())
    if alias:
        return alias
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return raw


def timezone_for(user_id: int | None, when: datetime | date | None = None) -> ZoneInfo:
    """Пояс участника на момент `when`. По умолчанию — общий TIMEZONE."""
    if user_id is None:
        return TIMEZONE
    periods = _periods().get(user_id)
    if not periods:
        return TIMEZONE

    if when is None:
        return periods[-1][1]

    # Момент приводим к общему поясу: нужна точка отсчёта, не зависящая от
    # того, какой пояс мы сейчас как раз и выбираем.
    moment = when.astimezone(TIMEZONE).date() if isinstance(when, datetime) else when

    current = TIMEZONE
    for since, tz in periods:
        if since <= moment:
            current = tz
        else:
            break
    return current


def set_for(user_id: int, tz_name: str, since: date) -> None:
    db.set_timezone_row(user_id, since, tz_name)
    invalidate()


def describe(user_id: int) -> list[tuple[date, str]]:
    """Периоды участника для показа в чате."""
    return [(since, str(tz)) for since, tz in _periods().get(user_id, [])]
