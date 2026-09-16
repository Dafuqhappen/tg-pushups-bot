import asyncio
import logging
from datetime import date, timedelta

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut

import db
import streak_rules
from config import CHAT_ID, DAILY_GOAL, EXCLUDED_USER_IDS, current_local_day
from quotes import random_motivational

log = logging.getLogger("pushups-bot")

# The RU VPS hits long RKN-style block windows on fresh TCP to
# api.telegram.org (long-poll keep-alive survives, new sends die). Retry
# with exponential backoff capped at 60s. With 30 attempts the total
# patience is ~36 minutes — covers most observed windows while keeping the
# delayed post still sensible to read in chat. Bumping connect_timeout
# wouldn't help — during a block window SYN is dropped, so waiting longer
# per attempt just makes each failure slower.
_SEND_RETRIES = 30
_SEND_BASE_DELAY = 3.0
_SEND_MAX_DELAY = 60.0


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
                delay = min(_SEND_BASE_DELAY * (2 ** i), _SEND_MAX_DELAY)
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


def format_medals(state) -> str:
    """Медали выводятся из рекорда, поэтому остаются даже после отдыха."""
    return "🏅" + "·".join(str(m) for m in state.medals) if state.medals else ""


def build_summary_text(day: date, states: dict[int, "streak_rules.StreakState"]) -> str:
    """Собрать текст сводки за `day`. Чистая функция — ничего не пишет."""
    counts = db.counts_for_day(day)
    # Юзеры из EXCLUDED_USER_IDS не появляются в публичной сводке (ни в
    # прошедших, ни в недотянувших) — по их собственной просьбе.
    counts = [r for r in counts if r["user_id"] not in EXCLUDED_USER_IDS]
    passed = [r for r in counts if r["count"] >= DAILY_GOAL]
    tried_failed = [r for r in counts if 0 < r["count"] < DAILY_GOAL]

    lines = [f"📅 итоги {day.strftime('%d.%m.%Y')}"]

    # Подарок — главная новость дня, поэтому идёт сразу под заголовком.
    gifted = sorted(
        ((r, states[r["user_id"]]) for r in counts
         if r["user_id"] in states and states[r["user_id"]].gift_today),
        key=lambda pair: -pair[1].gift_today,
    )
    if gifted:
        lines.append(
            "\n🎁 подарок сезона: стрик возвращён к личному рекорду, "
            "месячный пропуск обновлён. Дальше — только вперёд."
        )
        for r, st in gifted:
            lines.append(f"• {_display_name(r)} — {st.gift_today} 🔥")

    if passed:
        names = ", ".join(_display_name(r) for r in passed)
        lines.append(f"\n✅ норму взяли: {names}\n{PASSED_PHRASE}")
        lines.append("\nстрики:")
        # counts_for_day отдаёт порядок по числу кружков; для витрины стриков
        # логичнее сортировать по самому стрику.
        by_streak = sorted(
            (r for r in passed if r["user_id"] in states),
            key=lambda r: (-states[r["user_id"]].current, -states[r["user_id"]].best),
        )
        for r in by_streak:
            st = states.get(r["user_id"])
            if st is None:
                continue
            medals = format_medals(st)
            medals = f" {medals}" if medals else ""
            lines.append(
                f"• {_display_name(r)} — {st.current} 🔥{medals} "
                f"(рекорд {st.best}, всего {db.total_for_user(r['user_id'])})"
            )
    else:
        lines.append("\n😴 сегодня никто не добил до нормы")

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

    # Отдельная витрина для тех, кто ходит каждый день, но не добирает до
    # нормы: без неё их усилия отображаются как ноль, и люди отваливаются.
    passed_ids = {r["user_id"] for r in passed}
    walkers = sorted(
        (
            (r, states[r["user_id"]])
            for r in counts
            if r["user_id"] not in passed_ids
            and r["user_id"] in states
            and states[r["user_id"]].activity_current >= 2
        ),
        key=lambda pair: -pair[1].activity_current,
    )[:5]
    if walkers:
        lines.append("\n⚡ ходят стабильно (хотя бы один кружок в день):")
        for r, st in walkers:
            lines.append(f"• {_display_name(r)} — {st.activity_current} дней подряд")

    rescued = [
        (r, states[r["user_id"]])
        for r in counts
        if r["user_id"] in states
        and (states[r["user_id"]].freeze_spent_today
             or states[r["user_id"]].amnesty_spent_today)
    ]
    for r, st in rescued:
        what = "день отдыха" if st.freeze_spent_today else "месячный пропуск"
        left = st.rest_days(day)
        lines.append(
            f"\n🧊 {_display_name(r)} — стрик сохранён, списан {what} "
            f"(осталось дней отдыха: {left})"
        )

    for r in counts:
        st = states.get(r["user_id"])
        if st is not None and st.milestone_today:
            lines.append(
                f"\n🏅 веха взята: {_display_name(r)} — "
                f"{st.milestone_today} дней подряд!"
            )

    lines.append("\nправила — /rules · своя статистика — /stats")
    return "\n".join(lines)


async def post_daily_summary(bot: Bot) -> None:
    """Summarise yesterday's logical day (runs at SUMMARY_HOUR local time)."""
    # Сводка фиксированно подытоживает «вчерашний логический день».
    # Раньше day выводился из текущего времени минус минута — это работало,
    # пока время сводки совпадало с cutoff. После отвязки SUMMARY_HOUR от
    # DAY_CUTOFF_HOUR прямой расчёт через current_local_day - 1 надёжнее.
    day = current_local_day() - timedelta(days=1)

    # Полный реплей из video_notes: состояние самовосстанавливается, даже
    # если бот пропустил один или несколько дней.
    states = streak_rules.recompute_all(day)

    text = build_summary_text(day, states)
    await _send_with_retry(bot, chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_motivational()}")


async def post_motivational_quote(bot: Bot) -> None:
    await _send_with_retry(bot, chat_id=CHAT_ID, text=f"💬 {random_motivational()}")
