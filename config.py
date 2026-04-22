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

# "Day" runs from DAY_CUTOFF_HOUR:00 local to DAY_CUTOFF_HOUR:00 the next calendar date.
# Kruzhki sent before the cutoff are counted toward the *previous* day, and the
# daily summary job fires at DAY_CUTOFF_HOUR:00.
DAY_CUTOFF_HOUR = int(os.getenv("DAY_CUTOFF_HOUR", "9"))

TG_API_ID = os.getenv("TG_API_ID")
TG_API_HASH = os.getenv("TG_API_HASH")
TG_PHONE = os.getenv("TG_PHONE")
BACKFILL_SINCE = os.getenv("BACKFILL_SINCE", "2026-04-01")


def to_local_day(dt: datetime) -> date:
    """Map any timezone-aware datetime to the logical day under the cutoff rule."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(TIMEZONE) - timedelta(hours=DAY_CUTOFF_HOUR)).date()


def current_local_day() -> date:
    return to_local_day(datetime.now(timezone.utc))
