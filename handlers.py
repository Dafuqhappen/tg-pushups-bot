from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

import db
import streak_rules
from config import (
    CHAT_ID,
    DAILY_GOAL,
    DAY_CUTOFF_HOUR,
    EXCLUDED_USER_IDS,
    FREEZE_EVERY,
    MILESTONES,
    SEASON_START,
    SUMMARY_HOUR,
    current_local_day,
    to_local_day,
)


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

    user = msg.from_user
    today = current_local_day()
    # Стрик считается по закрытым дням, сегодняшний ещё идёт — поэтому
    # состояние берём на вчера, а текущий день показываем отдельно.
    st = streak_rules.state_for(user.id, today - timedelta(days=1))
    today_count = db.count_for_day(user.id, today)

    medals = " · ".join(str(m) for m in st.medals) if st.medals else "пока нет"
    amnesty = "свободен ✅" if st.amnesty_free(today) else "использован ❌"

    lines = [
        f"{_display_name(user)}",
        f"сегодня: {today_count}/{DAILY_GOAL}",
        "",
        f"🔥 стрик: {st.current} (рекорд {st.best})",
        f"🏅 медали: {medals}",
        f"⚡ активность: {st.activity_current} дней подряд "
        f"(рекорд {st.activity_best})",
        "",
        f"сезон с {SEASON_START.strftime('%d.%m.%Y')}:",
        f"• дней с нормой: {st.passed_days}",
        f"• активных дней: {st.active_days}",
        f"• кружков за сезон: {st.season_kruzhki}",
        f"• кружков за всё время: {db.total_for_user(user.id)}",
        "",
        f"🧊 отдых: {st.rest_days(today)} дн. доступно",
        f"• накоплено заморозок: {st.freeze_banked} "
        f"(+1 за каждые {FREEZE_EVERY} дней подряд)",
        f"• месячный пропуск: {amnesty}",
    ]
    await msg.reply_text("\n".join(lines))


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return

    today = current_local_day()
    states = streak_rules.recompute_all(today - timedelta(days=1), persist=False)

    rows = []
    for u in db.all_users():
        uid = u["user_id"]
        if uid in EXCLUDED_USER_IDS:
            continue
        st = states.get(uid)
        if st is None:
            continue
        name = u["first_name"] or (
            f"@{u['username']}" if u["username"] else f"id{uid}"
        )
        rows.append((name, st, db.total_for_user(uid)))

    rows.sort(key=lambda r: (-r[1].current, -r[1].best, -r[2]))

    lines = ["🏆 таблица:"]
    for name, st, total in rows:
        medals = "🏅" + "·".join(str(m) for m in st.medals) if st.medals else ""
        medals = f" {medals}" if medals else ""
        lines.append(
            f"• {name} — {st.current} 🔥{medals} "
            f"(рекорд {st.best}, всего {total})"
        )
    await msg.reply_text("\n".join(lines) if len(lines) > 1 else "пока пусто")


def build_rules_text() -> str:
    """Текст правил. Вынесен из хендлера, чтобы его можно было отрендерить
    и вычитать, не дёргая Telegram."""
    cutoff = f"{DAY_CUTOFF_HOUR:02d}:00"
    milestones = " · ".join(str(m) for m in MILESTONES)

    # Текст собирается из тех же констант, по которым живёт бот, — так
    # правила в чате физически не могут разойтись с поведением.
    lines = [
        "📖 правила",
        "",
        f"🎯 норма — {DAILY_GOAL} кружка в день.",
        "",
        f"🕕 день считается с {cutoff} до {cutoff} следующих суток.",
        f"   Кружок в 03:00 ночи попадёт во вчера, в 07:00 утра — в сегодня.",
        f"   Сводка за прошедший день выходит в {SUMMARY_HOUR:02d}:00,",
        "   цитаты — в 15:00 и 21:00.",
        "",
        "🔥 стрик — дни подряд, когда норма выполнена.",
        "   При пропуске списывается, по порядку:",
        "   1. бесплатный месячный пропуск (один на календарный месяц)",
        "   2. накопленный день заморозки",
        "   3. если ничего не осталось — стрик обнуляется",
        "   Пока стрика нет, пропуски ничего не тратят.",
        "",
        f"🧊 заморозка — +1 день отдыха за каждые {FREEZE_EVERY} дней подряд.",
        "   Копится и не сгорает. Тратится автоматически, когда месячный",
        "   пропуск за этот месяц уже израсходован.",
        "",
        f"🏅 медали — за вехи {milestones} дней подряд.",
        "   Считаются от рекорда, поэтому остаются навсегда:",
        "   отдых и обнуление стрика их не отнимают.",
        "",
        "⚡ активность — отдельный счётчик дней подряд хотя бы с одним",
        "   кружком. Живёт своей жизнью и показывает, что ты продолжаешь",
        "   ходить, даже когда до нормы не добрал.",
        "",
        "команды: /stats — своя статистика, /top — таблица, /rules — это сообщение",
    ]
    return "\n".join(lines)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return
    await msg.reply_text(build_rules_text())
