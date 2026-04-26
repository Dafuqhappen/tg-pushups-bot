"""One-off: re-send the daily summary that the scheduler failed to deliver.

Use case: scheduled 09:00 post died on network timeouts (streaks were
already updated as the first step of post_daily_summary, only the
send_message half failed). Run this to deliver the text post-hoc.

Usage:
    .venv/bin/python send_missed_summary.py            # вчерашний день
    .venv/bin/python send_missed_summary.py 2026-04-25 # явно
"""

import asyncio
import socket
import sys
from datetime import date, timedelta

from telegram import Bot
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID, current_local_day
from quotes import random_motivational
from scheduler import _send_with_retry, build_summary_text

# Force IPv4 — IPv6 route to api.telegram.org from this VPS sometimes hangs.
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **kw: [
    x for x in _orig_getaddrinfo(*a, **kw) if x[0] == socket.AF_INET
]


async def main() -> None:
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        day = current_local_day() - timedelta(days=1)

    text = build_summary_text(day)
    print(f"--- summary for {day.isoformat()} ---")
    print(text)
    print("--- end ---")

    req = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=20.0,
    )
    bot = Bot(token=BOT_TOKEN, request=req)
    async with bot:
        await _send_with_retry(bot, chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_motivational()}")
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
