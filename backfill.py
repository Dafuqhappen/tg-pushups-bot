"""One-off script: pull video-note history from the chat via a user account
and load it into the bot's SQLite database.

Usage:
    python backfill.py

Requires TG_API_ID / TG_API_HASH / TG_PHONE / CHAT_ID / BACKFILL_SINCE in .env.
Get API credentials at https://my.telegram.org → API development tools.
"""

import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo, MessageMediaDocument

import db
from config import (
    BACKFILL_SINCE,
    CHAT_ID,
    DAY_CUTOFF_HOUR,
    TG_API_HASH,
    TG_API_ID,
    TG_PHONE,
    TIMEZONE,
    to_local_day,
)


def _is_video_note(message) -> bool:
    # Telethon exposes a convenience property in recent versions
    if getattr(message, "video_note", None) is not None:
        return True
    if not isinstance(message.media, MessageMediaDocument):
        return False
    doc = message.media.document
    if doc is None:
        return False
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
            return True
    return False


async def run() -> None:
    if not (TG_API_ID and TG_API_HASH and TG_PHONE):
        raise SystemExit("Set TG_API_ID / TG_API_HASH / TG_PHONE in .env first")

    db.init_db()

    since_local = datetime.fromisoformat(BACKFILL_SINCE).replace(
        tzinfo=TIMEZONE, hour=DAY_CUTOFF_HOUR
    )
    since_utc = since_local.astimezone(timezone.utc)
    print(f"[backfill] since {since_utc.isoformat()} (UTC), chat_id={CHAT_ID}")

    async with TelegramClient("backfill", int(TG_API_ID), TG_API_HASH) as client:
        await client.start(phone=TG_PHONE)

        entity = await client.get_entity(CHAT_ID)
        print(f"[backfill] entity: {getattr(entity, 'title', entity)}")

        scanned = video_notes = inserted = skipped = 0

        # iterate newest → oldest, stop once we pass the since boundary
        async for msg in client.iter_messages(entity):
            scanned += 1
            if scanned % 500 == 0:
                print(
                    f"[backfill] scanned={scanned} video_notes={video_notes} "
                    f"inserted={inserted} last_date={msg.date.isoformat()}"
                )

            if msg.date < since_utc:
                print(f"[backfill] reached {msg.date.isoformat()} — stopping")
                break

            if not _is_video_note(msg):
                continue

            video_notes += 1

            sender = await msg.get_sender()
            if sender is None or getattr(sender, "bot", False):
                continue

            db.upsert_user(
                sender.id,
                getattr(sender, "username", None),
                getattr(sender, "first_name", None),
            )

            local_date = to_local_day(msg.date)
            if db.record_video_note(msg.id, sender.id, msg.date, local_date):
                inserted += 1
            else:
                skipped += 1

        print(
            f"[backfill] done. scanned={scanned} video_notes={video_notes} "
            f"inserted={inserted} skipped(dup)={skipped}"
        )


if __name__ == "__main__":
    asyncio.run(run())
