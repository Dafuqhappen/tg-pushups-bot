from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

import db
import streak_rules
import timezones
from config import (
    CHAT_ID,
    DAILY_GOAL,
    DAY_CUTOFF_HOUR,
    TIMEZONE,
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
    # День считается в поясе автора кружка: для одного и того же момента
    # у москвича это ещё вчера, а у участника восточнее — уже сегодня.
    local_date = to_local_day(sent_at, timezones.timezone_for(user.id, sent_at))
    db.record_video_note(msg.message_id, user.id, sent_at, local_date)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return

    user = msg.from_user
    today = current_local_day(timezones.timezone_for(user.id))
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
        "🌍 сутки считаются в твоём часовом поясе. Если переехал —",
        "   скажи боту: /timezone Нячанг. Иначе ранняя тренировка может",
        "   уехать во вчерашний день.",
        "",
        "команды: /stats — статистика, /top — таблица,",
        "/timezone — часовой пояс, /rules — это сообщение",
    ]
    return "\n".join(lines)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return
    await msg.reply_text(build_rules_text())


def _boundary_in_global_tz(tz) -> str:
    """Во сколько по общему поясу начинаются сутки участника."""
    today = date.today()
    local_start = datetime(today.year, today.month, today.day, DAY_CUTOFF_HOUR, tzinfo=tz)
    return local_start.astimezone(TIMEZONE).strftime("%H:%M")


async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or msg.chat_id != CHAT_ID:
        return

    user = msg.from_user
    args = context.args or []

    # Без аргументов — показать, что сейчас стоит.
    if not args:
        periods = timezones.describe(user.id)
        tz = timezones.timezone_for(user.id)
        lines = [
            "🌍 часовой пояс",
            "",
            f"сейчас: {tz}",
            f"сутки начинаются в {DAY_CUTOFF_HOUR:02d}:00 по твоему времени "
            f"(это {_boundary_in_global_tz(tz)} МСК)",
        ]
        if periods:
            lines.append("")
            lines.append("история:")
            for since, name in periods:
                lines.append(f"• с {since.strftime('%d.%m.%Y')} — {name}")
        lines += [
            "",
            "сменить: /timezone Нячанг",
            "задним числом: /timezone Нячанг 2026-10-12",
            "можно и IANA-именем: /timezone Asia/Ho_Chi_Minh",
        ]
        await msg.reply_text("\n".join(lines))
        return

    # Последний аргумент может быть датой начала действия.
    since = current_local_day(timezones.timezone_for(user.id))
    place_parts = list(args)
    try:
        since = date.fromisoformat(place_parts[-1])
        place_parts = place_parts[:-1]
    except ValueError:
        pass

    if not place_parts:
        await msg.reply_text("не понял, какой пояс. Пример: /timezone Нячанг")
        return

    name = timezones.resolve_name(" ".join(place_parts))
    if name is None:
        known = ", ".join(sorted(timezones.ALIASES)[:8])
        await msg.reply_text(
            f"не знаю такого места: {' '.join(place_parts)}\n\n"
            f"можно городом ({known}, …) "
            f"или IANA-именем вида Asia/Ho_Chi_Minh"
        )
        return

    timezones.set_for(user.id, name, since)

    # local_date проставляется один раз при записи кружка, поэтому смену
    # пояса надо применить к уже сохранённым дням, иначе она подействует
    # только на будущие.
    moved = 0
    for r in db.notes_for_user(user.id):
        sent_at = datetime.fromisoformat(r["sent_at"])
        tz = timezones.timezone_for(user.id, sent_at)
        new_ld = to_local_day(sent_at, tz)
        if new_ld.isoformat() != r["local_date"]:
            db.set_note_local_date(r["message_id"], user.id, new_ld)
            moved += 1

    states = streak_rules.recompute_all(current_local_day() - timedelta(days=1))
    st = states.get(user.id)

    lines = [
        f"🌍 пояс обновлён: {name}",
        f"действует с {since.strftime('%d.%m.%Y')}",
        f"сутки начинаются в {DAY_CUTOFF_HOUR:02d}:00 по твоему времени "
        f"(это {_boundary_in_global_tz(timezones.timezone_for(user.id))} МСК)",
    ]
    if moved:
        lines.append(f"пересчитано кружков: {moved}")
    if st is not None:
        lines.append(f"твой стрик: {st.current} 🔥")
    await msg.reply_text("\n".join(lines))
