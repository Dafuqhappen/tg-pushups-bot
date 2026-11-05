"""Поздравление с годовщиной чата + объявление выданных заморозок.

Список спасённых серий собирается из фактически посчитанного состояния,
поэтому в тексте не может оказаться того, чего нет в данных.

    python -m scripts.announce_anniversary           # черновик
    python -m scripts.announce_anniversary --send    # отправить
"""

import argparse
import asyncio
import socket
from datetime import timedelta

import db
import streak_rules
from config import (
    BOT_TOKEN,
    CHAT_ID,
    DAILY_GOAL,
    EXCLUDED_USER_IDS,
    FREEZE_GIFT_AMOUNT,
    FREEZE_GIFT_DATE,
    current_local_day,
)
from scheduler import _send_with_retry
from telegram import Bot
from telegram.request import HTTPXRequest

_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **kw: [
    x for x in _orig_getaddrinfo(*a, **kw) if x[0] == socket.AF_INET
]

GREETING = """🎂 Поздравляю всех участников чата с годом существования данного челленджа.

Все, кто принимал участие, превозмогал, делал, когда не хотелось, сила воли делает вам поклон.
Вы стали сильнее не только физически, но и морально.

дисциплина +5
мышцы груди +10
мышцы ног +7
мышцы кора +6
мышцы рук и спины +7
самоуважение +10"""


def stats_block() -> str:
    """Цифры за год. Берутся из базы, а не пишутся руками."""
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM video_notes").fetchone()[0]
        people = conn.execute("SELECT COUNT(DISTINCT user_id) FROM video_notes").fetchone()[0]
        days = conn.execute("SELECT COUNT(DISTINCT local_date) FROM video_notes").fetchone()[0]
        norms = conn.execute(
            "SELECT COUNT(*) FROM (SELECT local_date, user_id, COUNT(*) n"
            " FROM video_notes GROUP BY local_date, user_id HAVING n >= ?)",
            (DAILY_GOAL,),
        ).fetchone()[0]

    # Кружок идёт примерно минуту — удобная единица, чтобы объём стал осязаемым.
    hours = total // 60
    return "\n".join([
        "за год вместе:",
        f"🎥 {total} кружков — это около {hours} часов непрерывного видео",
        f"✅ {norms} закрытых норм",
        f"📆 {days} дней, когда в чате кто-то занимался",
        f"👥 {people} человек прошло через челлендж",
    ])


def build_text() -> str:
    if FREEZE_GIFT_DATE is None or FREEZE_GIFT_AMOUNT <= 0:
        raise SystemExit("FREEZE_GIFT_DATE / FREEZE_GIFT_AMOUNT не заданы в .env")

    yesterday = current_local_day() - timedelta(days=1)
    states = streak_rules.recompute_all(yesterday, persist=False)
    names = {
        u["user_id"]: (
            u["first_name"] or (f"@{u['username']}" if u["username"] else f"id{u['user_id']}")
        )
        for u in db.all_users()
    }

    alive = sorted(
        ((names.get(uid, uid), st) for uid, st in states.items()
         if uid not in EXCLUDED_USER_IDS and st.current > 0),
        key=lambda pair: -pair[1].current,
    )

    lines = [
        GREETING,
        "",
        stats_block(),
        "",
        f"🎁 В честь дня рождения чата всем начислено {FREEZE_GIFT_AMOUNT} несгораемых дней "
        f"(с {FREEZE_GIFT_DATE.strftime('%d.%m')}). Пропустил день — списывается "
        "несгораемый, а не серия.",
    ]
    if alive:
        lines += ["", "серии на сегодня:"]
        for name, st in alive:
            medals = " 🏅" + "·".join(str(m) for m in st.medals) if st.medals else ""
            lines.append(f"• {name} — {st.current} 🔥{medals} (🧊 {st.freeze_banked})")

    lines += ["", "правила — /rules · своя статистика — /stats"]
    return "\n".join(lines)


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
