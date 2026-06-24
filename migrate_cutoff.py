"""Migration: пересчитать local_date для всех video_notes под текущим
DAY_CUTOFF_HOUR (значит, после смены cutoff в .env / config.py).

Что делает:
  1. Бэкап SQLite файла.
  2. Для каждой записи video_notes пересчитывает local_date через
     to_local_day(sent_at) с новым cutoff. Обновляет только если изменилось.
  3. Запускает recount_streaks (сбрасывает state и пересчитывает стрики
     под новыми local_date + правилом monthly skip + правилом «сезон
     начинается с первого pass-дня»).

Usage:
    systemctl --user stop pushups-bot
    .venv/bin/python migrate_cutoff.py
    systemctl --user start pushups-bot

Идемпотентен — повторный запуск без изменения cutoff = no-op по данным.
"""

import shutil
from datetime import datetime
from pathlib import Path

import db
from config import DAY_CUTOFF_HOUR, DB_PATH, to_local_day
import recount_streaks


def main() -> None:
    print(f"using DAY_CUTOFF_HOUR={DAY_CUTOFF_HOUR}")

    src = Path(DB_PATH)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.parent / f"{src.name}.bak.{ts}"
    shutil.copy2(src, dst)
    print(f"backup → {dst}")

    db.init_db()

    changed = 0
    total = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT message_id, user_id, sent_at, local_date FROM video_notes"
        ).fetchall()
        total = len(rows)
        for r in rows:
            sent_at = datetime.fromisoformat(r["sent_at"])
            new_ld = to_local_day(sent_at).isoformat()
            if new_ld != r["local_date"]:
                conn.execute(
                    "UPDATE video_notes SET local_date = ?"
                    " WHERE message_id = ? AND user_id = ?",
                    (new_ld, r["message_id"], r["user_id"]),
                )
                changed += 1

    print(f"video_notes scanned={total} reassigned={changed}")

    # Сбрасываем per-user state, чтобы recount собрал стрики с нуля под
    # новыми local_date. best_streak сохраняется (это all-time пол).
    with db.connect() as conn:
        n = conn.execute(
            "UPDATE streaks SET current_streak = 0,"
            " last_passed_date = NULL,"
            " skip_used_month = NULL"
        ).rowcount
        print(f"reset state for {n} streak rows (best_streak preserved)")

    print()
    recount_streaks.recount()
    print("\nDONE")


if __name__ == "__main__":
    main()
