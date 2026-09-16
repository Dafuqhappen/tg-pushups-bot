"""Тесты правил стрика. Запуск: python test_streak_rules.py

Без pytest — правила это чистая функция, хватает assert-ов. Проверяются
именно те сценарии, на которых механика ломалась в проде: простой в начале
месяца, добивка нормы ночью, длинный отдых за счёт накопленных заморозок.
"""

import os
from datetime import date, timedelta

# config читает .env и требует BOT_TOKEN/CHAT_ID — подставляем заглушки,
# чтобы тест не зависел от окружения.
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("CHAT_ID", "-100")
os.environ.setdefault("DB_PATH", "/tmp/test-pushups-never-written.db")

from streak_rules import replay  # noqa: E402

START = date(2026, 6, 1)


def counts(seq, start=START):
    """[4, 0, 4] -> {1 июня: 4, 2 июня: 0, 3 июня: 4}"""
    return {start + timedelta(days=i): n for i, n in enumerate(seq)}


def run(seq, start=START, **kw):
    c = counts(seq, start)
    return replay(c, start + timedelta(days=len(seq) - 1), start=start, **kw)


failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: получили {got}, ожидали {want}")


# 1. Простая серия
st = run([4, 4, 4, 4, 4])
check("серия 5 дней", st.current, 5)
check("рекорд", st.best, 5)

# 2. Месячная амнистия спасает один пропуск
st = run([4, 4, 4, 0, 4, 4])
check("амнистия: стрик жив", st.current, 5)
check("амнистия: месяц помечен", st.amnesty_month, "2026-06")

# 3. Второй пропуск за месяц обнуляет
st = run([4, 4, 4, 0, 0, 4])
check("второй пропуск обнуляет", st.current, 1)

# 4. Простой до первого выполненного дня ничего не жжёт.
#    Это баг, из-за которого у участника сгорала амнистия 1-го числа.
st = run([0, 0, 0, 0, 4, 4, 0, 4])
check("простой в начале не тратит амнистию", st.current, 3)
check("амнистия потрачена только на реальный пропуск", st.amnesty_month, "2026-06")

# 5. Заморозка начисляется за каждые 30 дней подряд
st = run([4] * 60)
check("60 дней -> 2 заморозки", st.freeze_banked, 2)
check("60 дней -> медали 30 и 50", st.medals, [30, 50])

# 6. Заморозка тратится после амнистии, стрик выживает
st = run([4] * 30 + [0, 0] + [4])
check("отдых 2 дня: стрик продолжился", st.current, 31)
check("отдых 2 дня: заморозка списана", st.freeze_banked, 0)

# 7. Когда ресурсы кончились — стрик рвётся
st = run([4] * 30 + [0, 0, 0] + [4])
check("третий пропуск подряд рвёт стрик", st.current, 1)

# 8. Вехи объявляются один раз, в день достижения
st = run([4] * 30)
check("веха 30 в день достижения", st.milestone_today, 30)
st = run([4] * 31)
check("на следующий день веха не повторяется", st.milestone_today, None)

# 9. Активность считается отдельно от нормы
st = run([1, 1, 1, 1, 1])
check("активность растёт без нормы", st.activity_current, 5)
check("основной стрик при этом ноль", st.current, 0)
check("активность не тратит амнистию", st.amnesty_month, None)

# 10. Разрыв активности обнуляет её, но не задевает основной стрик
st = run([4, 4, 0, 4])
check("активность рвётся на нуле", st.activity_current, 1)
check("основной стрик пережил (амнистия)", st.current, 3)

# 11. Рекорды приходят полом из хранилища и не понижаются
st = run([4, 4], best_floor=55, activity_best_floor=40)
check("рекорд стрика не понижается", st.best, 55)
check("рекорд активности не понижается", st.activity_best, 40)
check("медали считаются от рекорда", st.medals, [30, 50])

# 12. Границы месяца: амнистия обновляется с новым месяцем
june = [4] * 29 + [0]          # 1-29 июня норма, 30-го пропуск (амнистия июня)
july = [4, 0, 4]               # 1 июля норма, 2-го пропуск (амнистия июля), 3-го норма
st = run(june + july)
# 29 выполненных дней июня + 1 и 3 июля = 31. Прощённые дни (30 июня,
# 2 июля) стрик сохраняют, но не наращивают.
check("новый месяц даёт новую амнистию", st.current, 31)
check("амнистия отмечена июлем", st.amnesty_month, "2026-07")

# 13. Счётчики за сезон
st = run([4, 2, 0, 5, 4])
check("дней с нормой", st.passed_days, 3)
check("активных дней", st.active_days, 4)
check("кружков за сезон", st.season_kruzhki, 15)

# 14. Разовый подарок сезона
import config  # noqa: E402
from datetime import date as _date  # noqa: E402

config.STREAK_GIFT_DATE = START + timedelta(days=5)
import streak_rules as _sr  # noqa: E402
_sr.STREAK_GIFT_DATE = config.STREAK_GIFT_DATE

# рекорд 4 в прошлом, потом развал; на шестой день — подарок.
# Период обрываем на дне подарка: дальше обновлённую амнистию уже может
# потратить следующий пропуск, и мы проверяли бы не то.
st = run([4, 4, 4, 4, 0, 0])
check("подарок поднимает стрик до рекорда", st.current, 4)
check("подарок обновляет месячную амнистию", st.amnesty_month, None)
check("подарок отмечен в состоянии", st.gift_today, 4)

# обновлённая амнистия реально работает на следующий день
st = run([4, 4, 4, 4, 0, 0, 0])
check("после подарка пропуск гасится амнистией", st.current, 4)

# у кого рекорд уже равен текущему — подарок ничего не меняет
st = run([4, 4, 4, 4, 4, 4, 4])
check("подарок не ломает живую серию", st.current, 7)

# после подарка стрик продолжает расти
st = run([4, 4, 4, 4, 0, 0, 4])
check("после подарка серия продолжается", st.current, 5)

# нечего дарить тому, кто ни разу не выполнил норму
st = run([0, 0, 0, 0, 0, 0, 0])
check("без рекорда дарить нечего", st.current, 0)

# веха от подарка не объявляется — цифра получена, а не набрана
st = run([4] * 30 + [0] * 5, best_floor=100)
check("подарок не объявляет веху", st.milestone_today, None)

_sr.STREAK_GIFT_DATE = None
config.STREAK_GIFT_DATE = None

if failures:
    print("ПРОВАЛЕНО:")
    for f in failures:
        print("  •", f)
    raise SystemExit(1)
print("✓ все проверки правил пройдены")
