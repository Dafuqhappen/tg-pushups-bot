import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut

import db
from config import CHAT_ID, DAILY_GOAL, to_local_day
from quotes import random_bros, random_motivational

log = logging.getLogger("pushups-bot")

# The VPS sometimes fails to open fresh outbound TCP connections to
# api.telegram.org for a few seconds at a time (existing keep-alive ones keep
# working). Retry scheduled sends with exponential backoff so a single hiccup
# doesn't cost us a post. Delays: 3, 6, 12, 24, 48 seconds.
_SEND_RETRIES = 5
_SEND_BASE_DELAY = 3.0


async def _send_with_retry(bot: Bot, **kwargs) -> None:
    last_err: Exception | None = None
    for i in range(_SEND_RETRIES):
        try:
            await bot.send_message(**kwargs)
            if i > 0:
                log.info("send_message succeeded on attempt %d", i + 1)
            return
        except (TimedOut, NetworkError) as e:
            last_err = e
            if i < _SEND_RETRIES - 1:
                delay = _SEND_BASE_DELAY * (2 ** i)
                log.warning(
                    "send_message attempt %d failed (%s); retrying in %.0fs",
                    i + 1, e, delay,
                )
                await asyncio.sleep(delay)
    assert last_err is not None
    raise last_err


PARTIAL_PHRASES: dict[int, str] = {
    1: "🌱 25% нормы — уже что-то. Завтра соберись.",
    2: "🌤 50% — ровно половина. Можно дотянуть.",
    3: "🔥 75% — один кружок до нормы, надо добить.",
}
PASSED_PHRASE = "🫵 100% — real push ups bro."


def _display_name(row) -> str:
    return row["first_name"] or (f"@{row['username']}" if row["username"] else f"id{row['user_id']}")


def build_summary_text(day: date) -> str:
    """Render the daily summary for `day` from current DB state. Pure — no writes."""
    counts = db.counts_for_day(day)
    passed = [r for r in counts if r["count"] >= DAILY_GOAL]
    tried_failed = [r for r in counts if 0 < r["count"] < DAILY_GOAL]

    lines = [f"📅 итоги {day.strftime('%d.%m.%Y')}"]

    if passed:
        names = ", ".join(_display_name(r) for r in passed)
        lines.append(f"\n✅ челлендж прошли: {names}\n{PASSED_PHRASE}")
    else:
        lines.append("\n😴 сегодня никто не добил до нормы")

    if passed:
        lines.append("\nстрики:")
        for r in passed:
            s = db.get_streak(r["user_id"])
            lines.append(
                f"• {_display_name(r)} — {s['current_streak']} 🔥 "
                f"(рекордный стрик {s['best_streak']}, "
                f"всего {db.total_for_user(r['user_id'])})"
            )

    if tried_failed:
        lines.append("\nне дотянули:")
        prev_count = None
        for r in tried_failed:
            if prev_count is not None and r["count"] != prev_count:
                lines.append("")
            phrase = PARTIAL_PHRASES.get(r["count"], "")
            line = f"• {_display_name(r)} — {r['count']}/{DAILY_GOAL}"
            if phrase:
                line += f"   {phrase}"
            lines.append(line)
            prev_count = r["count"]

    return "\n".join(lines)


async def post_daily_summary(bot: Bot) -> None:
    """Summarise the day that just ended (runs at DAY_CUTOFF_HOUR local time)."""
    # A moment 1 minute before the cutoff still belongs to the day that's wrapping up.
    day = to_local_day(datetime.now(timezone.utc) - timedelta(minutes=1))

    for row in db.counts_for_day(day):
        db.update_streak(row["user_id"], day, passed=row["count"] >= DAILY_GOAL)

    text = build_summary_text(day)
    await _send_with_retry(bot, chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_motivational()}")


async def post_motivational_quote(bot: Bot) -> None:
    await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_motivational()}")


async def post_bros_quote(bot: Bot) -> None:
    await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_bros()}")
