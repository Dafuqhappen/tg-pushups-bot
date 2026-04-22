import logging
from datetime import time

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

import db
from config import BOT_TOKEN, DAY_CUTOFF_HOUR, TIMEZONE
from handlers import cmd_stats, cmd_top, on_video_note
from scheduler import post_bros_quote, post_daily_summary, post_motivational_quote

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("pushups-bot")


async def _daily_job(context):
    await post_daily_summary(context.bot)


async def _bros_job(context):
    await post_bros_quote(context.bot)


async def _motivational_job(context):
    await post_motivational_quote(context.bot)


def main() -> None:
    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.VIDEO_NOTE, on_video_note))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))

    app.job_queue.run_daily(
        _daily_job,
        time=time(hour=DAY_CUTOFF_HOUR, minute=0, tzinfo=TIMEZONE),
        name="daily_summary",
    )

    app.job_queue.run_daily(
        _bros_job,
        time=time(hour=15, minute=0, tzinfo=TIMEZONE),
        name="bros_quote_15",
    )
    app.job_queue.run_daily(
        _motivational_job,
        time=time(hour=21, minute=0, tzinfo=TIMEZONE),
        name="motivational_quote_21",
    )

    log.info("bot started")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
