import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("pushups-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
DAILY_GOAL = int(os.getenv("DAILY_GOAL", "4"))
DB_PATH = os.getenv("DB_PATH", "data/pushups.db")

# Граница «логического дня» в ЛИЧНОМ поясе участника. Кружок, посланный
# после DAY_CUTOFF_HOUR, относится к сегодня; до — к предыдущему дню.
#
# Cutoff = 5 покрывает оба реальных сценария чата:
#   - добивка нормы ночью (00–05) засчитывается за «вчера»;
#   - ранняя тренировка (05–09) засчитывается за «сегодня».
# История значения: 9 (ломало утренних) → 3 (ломало ночных) → 6 → 5.
# Переход 6→5 безопасен: в окне 05:00–08:00 не слал никто.
DAY_CUTOFF_HOUR = int(os.getenv("DAY_CUTOFF_HOUR", "5"))

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

# Каждые FREEZE_EVERY дней подряд участник зарабатывает один день заморозки.
# Заморозка тратится на пропуск автоматически — после того, как исчерпана
# бесплатная месячная амнистия. Смысл: право на отдых достаётся тем, кто
# набрал длинную серию, и его нельзя получить, не сделав работу.
FREEZE_EVERY = int(os.getenv("FREEZE_EVERY", "30"))

# Вехи, за которые выдаются постоянные медали. Считаются от best_streak,
# поэтому остаются с человеком навсегда — отдых их не отнимает.
MILESTONES: tuple[int, ...] = tuple(
    int(x) for x in os.getenv("MILESTONES", "30,50,100,200,365").split(",") if x.strip()
)

# Разовый подарок сезона. В указанный день стрик каждого участника
# поднимается до его личного рекорда, день засчитывается выполненным, а
# месячная амнистия обновляется — иначе у тех, кто её уже потратил,
# подарок сгорел бы на первом же пропуске.
# Это часть правил, а не правка в БД: состояние пересобирается реплеем,
# поэтому разовый UPDATE затёрло бы следующим же пересчётом.
# Пустое значение — подарка нет.
_gift = os.getenv("STREAK_GIFT_DATE", "").strip()
STREAK_GIFT_DATE: date | None = date.fromisoformat(_gift) if _gift else None


# Карта «user_id → часовой пояс» из env. Нужна, потому что участники живут
# в разных поясах: один и тот же момент времени для москвича — глубокая ночь
# вчерашнего дня, а для участника из Алматы — раннее утро сегодняшнего.
# Без этого любой глобальный cutoff неизбежно обманывает одну из сторон.
# Формат: "273430899=Asia/Almaty,649321982=Europe/Berlin"
def _parse_user_timezones(raw: str) -> dict[int, tuple[ZoneInfo, date | None]]:
    """Разобрать карту персональных поясов из строки env.

    Формат записи: `id=Зона` либо `id=Зона@ГГГГ-ММ-ДД`. Дата — момент,
    с которого пояс вступает в силу; раньше неё кружки считаются по общему
    TIMEZONE. Без даты пояс действует на всю историю.

    Битые записи пропускаются с предупреждением, а не роняют процесс:
    опечатка в поясе одного участника не должна останавливать бота для
    всех остальных. Цена — такой участник молча считается по общему
    TIMEZONE, поэтому предупреждение стоит проверять в логе после правки.
    """
    out: dict[int, tuple[ZoneInfo, date | None]] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            log.warning("USER_TIMEZONES: пропущена запись без '=': %r", part)
            continue
        raw_id, raw_rest = (x.strip() for x in part.split("=", 1))
        raw_tz, _, raw_since = (x.strip() for x in raw_rest.partition("@"))

        # Разбираем по отдельности: ZoneInfo на кривом ключе тоже умеет
        # бросать ValueError, и в общем try ошибка списалась бы на user_id.
        try:
            uid = int(raw_id)
        except ValueError:
            log.warning("USER_TIMEZONES: нечисловой user_id в %r", part)
            continue
        try:
            tz = ZoneInfo(raw_tz)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("USER_TIMEZONES: неизвестный часовой пояс %r", raw_tz)
            continue
        since: date | None = None
        if raw_since:
            try:
                since = date.fromisoformat(raw_since)
            except ValueError:
                log.warning("USER_TIMEZONES: нечитаемая дата %r в %r", raw_since, part)
                continue
        out[uid] = (tz, since)
    return out


USER_TIMEZONES: dict[int, ZoneInfo] = _parse_user_timezones(
    os.getenv("USER_TIMEZONES", "")
)


def user_timezone(user_id: int | None, when: datetime | date | None = None) -> ZoneInfo:
    """Пояс участника на момент `when`; у кого не задан — общий TIMEZONE.

    Пояс с датой начала не применяется к более ранним кружкам. Иначе смена
    пояса переписывала бы прошлое: человек ориентировался на показания бота
    по старому правилу, останавливался на 4/4 — и ретроактивный пересчёт
    задним числом отнимал бы у него эти дни.
    """
    entry = USER_TIMEZONES.get(user_id) if user_id is not None else None
    if entry is None:
        return TIMEZONE
    tz, since = entry
    if since is None or when is None:
        return tz
    # Сравниваем по общему поясу: нужна стабильная точка отсчёта, не
    # зависящая от того, какой пояс мы сейчас выбираем.
    moment = when.astimezone(TIMEZONE).date() if isinstance(when, datetime) else when
    return tz if moment >= since else TIMEZONE


def to_local_day(dt: datetime, tz: ZoneInfo | None = None) -> date:
    """Сопоставить момент времени логическому дню по правилу cutoff.

    `tz` — пояс, в котором считается день. По умолчанию общий TIMEZONE;
    для кружка надо передавать пояс его автора.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(tz or TIMEZONE) - timedelta(hours=DAY_CUTOFF_HOUR)).date()


def current_local_day(tz: ZoneInfo | None = None) -> date:
    return to_local_day(datetime.now(timezone.utc), tz)
