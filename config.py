import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
DAILY_GOAL = int(os.getenv("DAILY_GOAL", "4"))
DB_PATH = os.getenv("DB_PATH", "data/pushups.db")

# Граница «логического дня». Любой кружок, посланный после DAY_CUTOFF_HOUR
# (по локальному TZ), относится к сегодня; до cutoff — к предыдущему дню.
# Cutoff = 3 МСК даёт удобный баланс: ранние тренировки утром (06–09)
# попадают в «сегодня», а поздние ночные (00–03) ещё засчитываются за
# «вчера». В прошлом было 9, но это ломало стрики тем, кто тренируется
# до завтрака.
DAY_CUTOFF_HOUR = int(os.getenv("DAY_CUTOFF_HOUR", "3"))

# Час, в который бот публикует ежедневную сводку за предыдущий логический
# день. Отделён от DAY_CUTOFF_HOUR, чтобы пост приходил в удобное время
# (09:00 МСК), а граница дня могла быть раньше.
SUMMARY_HOUR = int(os.getenv("SUMMARY_HOUR", "9"))

TG_API_ID = os.getenv("TG_API_ID")
TG_API_HASH = os.getenv("TG_API_HASH")
TG_PHONE = os.getenv("TG_PHONE")
BACKFILL_SINCE = os.getenv("BACKFILL_SINCE", "2026-04-01")

# Опциональный прокси для исходящих запросов к api.telegram.org.
# Нужен когда VPS в РФ и провайдер режет TLS до Telegram. Примеры значений:
#   http://user:pass@host:port
#   https://user:pass@host:port
#   socks5://user:pass@host:port   (требует: pip install "httpx[socks]")
# Если переменная не задана — прокси не используется.
TG_PROXY_URL = os.getenv("TG_PROXY_URL") or None


def _parse_user_id_set(raw: str) -> frozenset[int]:
    """Parse comma-separated user_id list from env. Ignores blanks and bad ints."""
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            pass
    return frozenset(out)


# Юзеры, которых бот игнорит в публичных подсчётах: не появляются в утренней
# сводке, в /top, и их стрики не обновляются (так что не «провисают»).
# Кружки в БД продолжают писаться, личный /stats показывает их данные как есть.
# Формат: "123,456,789".
EXCLUDED_USER_IDS: frozenset[int] = _parse_user_id_set(os.getenv("EXCLUDED_USER_IDS", ""))

# Дата старта текущего «сезона» — с неё начинается отсчёт стрика под новыми
# правилами (1 пропуск/месяц прощается, 2-й обнуляет). Кружки в БД до этой
# даты остаются, но в стрик не влияют. best_streak (all-time рекорд) при
# пересчёте сохраняется как пол.
SEASON_START = date.fromisoformat(os.getenv("SEASON_START", "2026-06-01"))


def to_local_day(dt: datetime) -> date:
    """Map any timezone-aware datetime to the logical day under the cutoff rule."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(TIMEZONE) - timedelta(hours=DAY_CUTOFF_HOUR)).date()


def current_local_day() -> date:
    return to_local_day(datetime.now(timezone.utc))
