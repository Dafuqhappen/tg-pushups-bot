from telegram import Update
from telegram.ext import ContextTypes

import db
from config import CHAT_ID, DAILY_GOAL, current_local_day, to_local_day


def _display_name(user) -> str:
    return user.first_name or (f"@{user.username}" if user.username else f"id{user.id}")


async def on_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID or msg.video_note is None:
        return

    user = msg.from_user
    if user is None or user.is_bot:
        return

    db.upsert_user(user.id, user.username, user.first_name)

    sent_at = msg.date
    local_date = to_local_day(sent_at)
    db.record_video_note(msg.message_id, user.id, sent_at, local_date)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return

    today = current_local_day()
    user = msg.from_user
    today_count = db.count_for_day(user.id, today)
    total = db.total_for_user(user.id)
    streak = db.get_streak(user.id)
    current = streak["current_streak"] if streak else 0
    best = streak["best_streak"] if streak else 0

    await msg.reply_text(
        f"{_display_name(user)}\n"
        f"сегодня: {today_count}/{DAILY_GOAL}\n"
        f"всего кружков: {total}\n"
        f"текущий стрик: {current} 🔥\n"
        f"рекордный стрик: {best}"
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return

    users = db.all_users()
    rows = []
    for u in users:
        streak = db.get_streak(u["user_id"])
        total = db.total_for_user(u["user_id"])
        name = u["first_name"] or (
            f"@{u['username']}" if u["username"] else f"id{u['user_id']}"
        )
        rows.append(
            (
                name,
                streak["current_streak"] if streak else 0,
                streak["best_streak"] if streak else 0,
                total,
            )
        )
    rows.sort(key=lambda r: (-r[1], -r[3]))

    lines = ["🏆 таблица:"]
    for name, cur, best, total in rows:
        lines.append(f"• {name} — стрик {cur} (рекордный стрик {best}), всего {total}")
    await msg.reply_text("\n".join(lines) if len(lines) > 1 else "пока пусто")
