"""Разовое объявление подарка сезона в чат.

Текст собирается из фактически посчитанного состояния, а не пишется руками,
поэтому цифры в объявлении гарантированно совпадают с тем, что покажут
/stats и /top.

    python announce_gift.py           # только показать текст
    python announce_gift.py --send    # отправить в чат
"""

import argparse
import asyncio
import socket
from collections import defaultdict

from telegram import Bot
from telegram.request import HTTPXRequest

import db
import streak_rules
from config import BOT_TOKEN, CHAT_ID, EXCLUDED_USER_IDS, STREAK_GIFT_DATE
from scheduler import _send_with_retry

# Force IPv4 — IPv6 route to api.telegram.org sometimes hangs.
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **kw: [
    x for x in _orig_getaddrinfo(*a, **kw) if x[0] == socket.AF_INET
]


def build_text() -> str:
    if STREAK_GIFT_DATE is None:
        raise SystemExit("STREAK_GIFT_DATE не задан в .env")

    states = streak_rules.recompute_all(STREAK_GIFT_DATE, persist=False)
    names = {
        u["user_id"]: (
            u["first_name"] or (f"@{u['username']}" if u["username"] else f"id{u['user_id']}")
        )
        for u in db.all_users()
    }

    # Группируем по величине подарка: одинаковые цифры в одну строку,
    # иначе список из 11 человек занимает пол-экрана.
    by_value: dict[int, list[str]] = defaultdict(list)
    for uid, st in states.items():
        if uid in EXCLUDED_USER_IDS or not st.gift_today:
            continue
        by_value[st.gift_today].append(names.get(uid, str(uid)))

    lines = [
        "🎁 подарок осеннего сезона",
        "",
        "Стрик каждого возвращён к личному рекорду, месячный пропуск "
        "обновлён. Цифра снова ваша — осталось её продлить.",
        "",
    ]
    for value in sorted(by_value, reverse=True):
        who = " · ".join(sorted(by_value[value]))
        lines.append(f"• {who} — {value} 🔥")

    lines += [
        "",
        "Заодно поменялись правила — теперь отдыхать можно, не теряя всё:",
        "",
        "🧊 за каждые 30 дней подряд копится день заморозки. Пропустил — "
        "списывается он, а не стрик.",
        "🏅 за 30 / 50 / 100 / 200 / 365 дней выдаётся медаль. Считается от "
        "рекорда, поэтому остаётся навсегда: отдых её не отнимает.",
        "⚡ появился отдельный счётчик дней подряд хотя бы с одним кружком — "
        "чтобы усилия тех, кто ходит, но не добирает до нормы, не выглядели "
        "нулём.",
        "",
        "Полные правила — /rules, своя статистика — /stats",
    ]
    return "\n".join(lines)


async def send(text: str) -> None:
    req = HTTPXRequest(
        connect_timeout=20.0, read_timeout=20.0, write_timeout=20.0, pool_timeout=20.0
    )
    bot = Bot(token=BOT_TOKEN, request=req)
    async with bot:
        await _send_with_retry(bot, chat_id=CHAT_ID, text=text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="отправить в чат")
    args = parser.parse_args()

    text = build_text()
    print("=" * 60)
    print(text)
    print("=" * 60)

    if args.send:
        print("\n[отправляю в чат...]")
        asyncio.run(send(text))
        print("OK — отправлено")
    else:
        print("\n(черновик — для отправки добавь --send)")


if __name__ == "__main__":
    main()
