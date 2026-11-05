"""Объявление о механике паузы серии.

Числа берутся из конфига, а не вписаны в текст, — иначе объявление
разойдётся с поведением бота, как только лимиты поменяются.

    python -m scripts.announce_pause           # черновик
    python -m scripts.announce_pause --send    # отправить
"""

import argparse
import asyncio
import socket

from config import BOT_TOKEN, CHAT_ID, PAUSE_BACKDATE_DAYS, PAUSE_BUDGET_DAYS
from scheduler import _send_with_retry
from telegram import Bot
from telegram.request import HTTPXRequest

_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **kw: [
    x for x in _orig_getaddrinfo(*a, **kw) if x[0] == socket.AF_INET
]


def build_text() -> str:
    return "\n".join([
        "🤕 Новое: пауза серии",
        "",
        "Заболел, травмировался, попал в больницу — теперь это не стоит вам серии. "
        "Дни на паузе просто не оцениваются: серия не растёт, но и не рвётся.",
        "",
        "Что важно:",
        "• месячный пропуск и накопленные заморозки за время паузы не тратятся",
        "• заниматься не запрещено — сделаете норму на паузе, день зачтётся "
        "обычным порядком и серия вырастет",
        "• пока пауза активна, она видна всем в утренней сводке",
        "",
        f"Бюджет — {PAUSE_BUDGET_DAYS} дней в календарный год на человека.",
        "",
        "Команды:",
        "/pause 14 порваны связки — уйти на две недели",
        "/pause — сколько осталось в бюджете",
        "/pause stop — вернуться раньше, неизрасходованное не сгорит",
        "",
        "Две оговорки:",
        "• паузу нельзя взять, когда серия уже 0 — она защищает живую, "
        "а не воскрешает потерянную",
        f"• задним числом можно уйти максимум на {PAUSE_BACKDATE_DAYS} дня назад",
        "",
        "Это не способ отдохнуть от челленджа, а способ не потерять месяцы "
        "работы из-за того, что от вас не зависит. Берегите себя.",
        "",
        "полные правила — /rules",
    ])


async def send(text: str) -> None:
    req = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0, write_timeout=20.0, pool_timeout=20.0)
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
        print("\n[отправляю...]")
        asyncio.run(send(text))
        print("OK — отправлено")
    else:
        print("\n(черновик — для отправки добавь --send)")


if __name__ == "__main__":
    main()
