from datetime import date, datetime, timedelta, timezone

from telegram import Bot
from telegram.constants import ParseMode

import db
from config import CHAT_ID, DAILY_GOAL, to_local_day
from quotes import random_bros, random_motivational


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
        lines.append(f"\n✅ челлендж прошли: {names}\nтак держать! 💪")
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
        for r in tried_failed:
            lines.append(f"• {_display_name(r)} — {r['count']}/{DAILY_GOAL}")

    return "\n".join(lines)


async def post_daily_summary(bot: Bot) -> None:
    """Summarise the day that just ended (runs at DAY_CUTOFF_HOUR local time)."""
    # A moment 1 minute before the cutoff still belongs to the day that's wrapping up.
    day = to_local_day(datetime.now(timezone.utc) - timedelta(minutes=1))

    for row in db.counts_for_day(day):
        db.update_streak(row["user_id"], day, passed=row["count"] >= DAILY_GOAL)

    text = build_summary_text(day)
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    await bot.send_message(chat_id=CHAT_ID, text=f"💬 {random_motivational()}")


async def post_motivational_quote(bot: Bot) -> None:
    await bot.send_message(chat_id=CHAT_ID, text=f"💬 {random_motivational()}")


async def post_bros_quote(bot: Bot) -> None:
    await bot.send_message(chat_id=CHAT_ID, text=f"💬 {random_bros()}")
