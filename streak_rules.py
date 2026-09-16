"""Правила стриков — чистая логика без обращений к БД.

Модуль получает на вход подневные счётчики кружков и проигрывает сезон
день за днём. Вынесение правил из хранилища даёт две вещи: ежедневная
джоба и офлайновый пересчёт используют одну реализацию и не могут
разъехаться, а сами правила можно гонять без базы.

Порядок применения на пропущенном дне: сначала бесплатная месячная
амнистия, затем накопленная заморозка, и только потом обнуление.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import db
from config import (
    DAILY_GOAL,
    FREEZE_EVERY,
    MILESTONES,
    SEASON_START,
)


@dataclass
class StreakState:
    """Состояние участника на конец проигранного периода."""

    current: int = 0
    best: int = 0
    last_passed: date | None = None

    activity_current: int = 0
    activity_best: int = 0
    last_active: date | None = None

    freeze_banked: int = 0
    amnesty_month: str | None = None

    passed_days: int = 0
    active_days: int = 0
    season_kruzhki: int = 0

    # Что случилось именно в последний проигранный день — нужно сводке.
    milestone_today: int | None = None
    freeze_spent_today: bool = False
    amnesty_spent_today: bool = False
    streak_broken_today: bool = False

    @property
    def medals(self) -> list[int]:
        """Пройденные вехи. Выводятся из best, поэтому не сгорают никогда."""
        return [m for m in MILESTONES if self.best >= m]

    def amnesty_free(self, day: date) -> bool:
        return self.amnesty_month != day.strftime("%Y-%m")

    def rest_days(self, day: date) -> int:
        """Сколько дней отдыха доступно прямо сейчас."""
        return self.freeze_banked + (1 if self.amnesty_free(day) else 0)


def replay(
    counts: dict[date, int],
    upto: date,
    *,
    start: date = SEASON_START,
    best_floor: int = 0,
    activity_best_floor: int = 0,
) -> StreakState:
    """Проиграть сезон с `start` по `upto` включительно.

    `best_floor` и `activity_best_floor` — всё-время рекорды из хранилища.
    Пересчёт может их только поднять, но не опустить: сезон короче истории,
    и достижения до его начала терять нельзя.
    """
    st = StreakState(best=best_floor, activity_best=activity_best_floor)
    joined = False

    day = start
    while day <= upto:
        n = counts.get(day, 0)
        passed = n >= DAILY_GOAL
        active = n > 0
        month = day.strftime("%Y-%m")

        st.season_kruzhki += n
        if active:
            st.active_days += 1
        if passed:
            st.passed_days += 1

        st.milestone_today = None
        st.freeze_spent_today = False
        st.amnesty_spent_today = False
        st.streak_broken_today = False

        # --- основной стрик (норма выполнена) ---
        if not joined and not passed:
            # Сезон участника ещё не начался: до первого выполненного дня
            # простои не считаются пропусками и ничего не жгут.
            pass
        elif passed:
            joined = True
            st.current += 1
            if st.current % FREEZE_EVERY == 0:
                st.freeze_banked += 1
            if st.current in MILESTONES and st.current > st.best:
                st.milestone_today = st.current
            st.best = max(st.best, st.current)
            st.last_passed = day
        elif st.current == 0:
            # Стрика нет — защищать нечего, ресурсы не тратим.
            pass
        elif st.amnesty_free(day):
            st.amnesty_month = month
            st.amnesty_spent_today = True
        elif st.freeze_banked > 0:
            st.freeze_banked -= 1
            st.freeze_spent_today = True
        else:
            st.current = 0
            st.streak_broken_today = True

        # --- стрик активности (хотя бы один кружок) ---
        if active:
            st.activity_current += 1
            st.activity_best = max(st.activity_best, st.activity_current)
            st.last_active = day
        else:
            st.activity_current = 0

        day += timedelta(days=1)

    return st


def state_for(user_id: int, upto: date) -> StreakState:
    """Состояние одного участника. Считается на лету, не зависит от того,
    успела ли отработать ежедневная джоба."""
    prev = db.get_streak(user_id)
    return replay(
        db.counts_by_day(user_id),
        upto,
        best_floor=(prev["best_streak"] if prev else 0) or 0,
        activity_best_floor=(prev["best_activity_streak"] if prev else 0) or 0,
    )


def recompute_all(upto: date, *, persist: bool = True) -> dict[int, StreakState]:
    """Пересчитать всех. Один запрос за счётчиками, дальше — в памяти."""
    counts = db.counts_by_day_all()
    states: dict[int, StreakState] = {}

    for u in db.all_users():
        uid = u["user_id"]
        prev = db.get_streak(uid)
        st = replay(
            counts.get(uid, {}),
            upto,
            best_floor=(prev["best_streak"] if prev else 0) or 0,
            activity_best_floor=(prev["best_activity_streak"] if prev else 0) or 0,
        )
        if persist:
            db.save_state(uid, st)
        states[uid] = st

    return states
