"""Пересчитать стрики всех участников по данным video_notes.

Вся логика правил живёт в streak_rules.replay — здесь только запуск и вывод.
Запускать после любых изменений video_notes мимо живого бота (бэкфилл,
смена DAY_CUTOFF_HOUR) или просто чтобы убедиться, что состояние сходится.

Usage:
    python recount_streaks.py
"""

from datetime import timedelta

import db
import streak_rules
from config import current_local_day


def recount() -> None:
    db.init_db()

    upto = current_local_day() - timedelta(days=1)
    states = streak_rules.recompute_all(upto)

    names = {u["user_id"]: (u["username"] or u["first_name"] or f"id{u['user_id']}")
             for u in db.all_users()}
    print(f"[recount] {len(states)} users, по {upto} включительно")

    for uid, st in sorted(states.items(), key=lambda kv: -kv[1].current):
        medals = ",".join(str(m) for m in st.medals) or "—"
        print(
            f"  {names.get(uid, uid)}: current={st.current} best={st.best}"
            f" act={st.activity_current} freeze={st.freeze_banked}"
            f" medals={medals} last_passed={st.last_passed or '—'}"
            f" amnesty={st.amnesty_month or '—'}"
        )

    print("[recount] done")


if __name__ == "__main__":
    recount()
