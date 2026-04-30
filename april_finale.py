"""April finale — end-of-month wrap-up post.

Preview (default, does NOT send):
    .venv/bin/python april_finale.py

Actually post to chat:
    .venv/bin/python april_finale.py --send
"""

import argparse
import asyncio
import socket
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from telegram import Bot
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID, DAILY_GOAL, TIMEZONE
from db import connect
from scheduler import _send_with_retry

# Force IPv4 — IPv6 route to api.telegram.org from this RU VPS hangs.
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **kw: [
    x for x in _orig_getaddrinfo(*a, **kw) if x[0] == socket.AF_INET
]

APRIL_START = date(2026, 4, 1)
APRIL_END = date(2026, 4, 30)
DAYS_IN_APRIL = (APRIL_END - APRIL_START).days + 1  # 30

# Исключаются и из рейтинга, и из «не записывали», и из «интересного».
# Сравнение по тому, что выводит display_name (first_name → @username → id<n>).
EXCLUDED_NAMES = {"Саня Саныч"}

RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

# Hour buckets for "когда чаще всего кидал" superlatives.
BUCKETS = [
    ("00-06", 0, 6, "ночью (00:00–06:00)"),
    ("06-12", 6, 12, "утром (06:00–12:00)"),
    ("12-16", 12, 16, "днём (12:00–16:00)"),
    ("16-20", 16, 20, "вечером (16:00–20:00)"),
    ("20-24", 20, 24, "поздно вечером (20:00–24:00)"),
]

MEDALS = ["🥇", "🥈", "🥉"]


def display_name(row) -> str:
    return row["first_name"] or (
        f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
    )


def fmt_ru_date(d: date) -> str:
    return f"{d.day} {RU_MONTHS[d.month]}"


def parse_msk(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TIMEZONE)


def fetch():
    with connect() as conn:
        users = {r["user_id"]: r for r in conn.execute("SELECT * FROM users").fetchall()}
        notes = conn.execute(
            "SELECT * FROM video_notes WHERE local_date BETWEEN ? AND ?",
            (APRIL_START.isoformat(), APRIL_END.isoformat()),
        ).fetchall()
        streaks = {r["user_id"]: r for r in conn.execute("SELECT * FROM streaks").fetchall()}

    # Отсекаем исключённых сразу на входе — дальше они нигде не появятся.
    excluded_ids = {uid for uid, u in users.items() if display_name(u) in EXCLUDED_NAMES}
    if excluded_ids:
        users = {uid: u for uid, u in users.items() if uid not in excluded_ids}
        notes = [n for n in notes if n["user_id"] not in excluded_ids]
        streaks = {uid: s for uid, s in streaks.items() if uid not in excluded_ids}

    return users, notes, streaks


def compute_stats(users, notes, streaks):
    by_user: dict[int, list] = defaultdict(list)
    for n in notes:
        by_user[n["user_id"]].append(n)

    stats = {}
    for uid, urows in by_user.items():
        msk = [parse_msk(n["sent_at"]) for n in urows]
        per_day = Counter(n["local_date"] for n in urows)

        bucket_dist: Counter = Counter()
        for dt in msk:
            for key, lo, hi, _ in BUCKETS:
                if lo <= dt.hour < hi:
                    bucket_dist[key] += 1
                    break

        best_day = max(per_day, key=per_day.get)
        sr = streaks.get(uid)

        stats[uid] = {
            "user_id": uid,
            "name": display_name(users[uid]),
            "total": len(urows),
            "active_days": len(per_day),
            "passed_days": sum(1 for c in per_day.values() if c >= DAILY_GOAL),
            "best_single_day": per_day[best_day],
            "best_single_day_date": date.fromisoformat(best_day),
            "first_kruzhok": min(msk),
            "last_kruzhok": max(msk),
            "bucket_dist": bucket_dist,
            "best_streak": sr["best_streak"] if sr else 0,
            "current_streak": sr["current_streak"] if sr else 0,
        }
    return stats


def assign_facts(stats):
    """Each user gets at most one distinguishing fact. Each title awarded once."""
    facts: dict[int, str] = {}
    used: set[int] = set()
    if not stats:
        return facts

    # 1. Latest joiner — only if joined ≥5 days after earliest
    by_first = sorted(stats.values(), key=lambda s: s["first_kruzhok"])
    earliest, latest = by_first[0], by_first[-1]
    gap = (latest["first_kruzhok"].date() - earliest["first_kruzhok"].date()).days
    if gap >= 5:
        facts[latest["user_id"]] = (
            f"присоединился позже всех — {fmt_ru_date(latest['first_kruzhok'].date())}"
        )
        used.add(latest["user_id"])

    # 2. Best streak (≥3)
    cands = [s for s in stats.values() if s["user_id"] not in used and s["best_streak"] >= 3]
    if cands:
        w = max(cands, key=lambda s: s["best_streak"])
        facts[w["user_id"]] = f"самая длинная серия — {w['best_streak']} дней подряд 🔥"
        used.add(w["user_id"])

    # 3. Best single day (> DAILY_GOAL)
    cands = [s for s in stats.values() if s["user_id"] not in used and s["best_single_day"] > DAILY_GOAL]
    if cands:
        w = max(cands, key=lambda s: s["best_single_day"])
        facts[w["user_id"]] = (
            f"лучший день месяца — {w['best_single_day']} кружков {fmt_ru_date(w['best_single_day_date'])}"
        )
        used.add(w["user_id"])

    # 4. Bucket champions
    for key, _, _, label in BUCKETS:
        cands = [
            s for s in stats.values()
            if s["user_id"] not in used and s["bucket_dist"].get(key, 0) >= 3
        ]
        if not cands:
            continue
        w = max(cands, key=lambda s: s["bucket_dist"].get(key, 0))
        cnt = w["bucket_dist"].get(key, 0)
        share = cnt / w["total"]
        if share >= 0.4:
            facts[w["user_id"]] = f"чаще всех кидал {label} — {cnt} из {w['total']} кружков"
            used.add(w["user_id"])

    # 5. Most active days (≥5)
    cands = [s for s in stats.values() if s["user_id"] not in used and s["active_days"] >= 5]
    if cands:
        w = max(cands, key=lambda s: s["active_days"])
        facts[w["user_id"]] = f"был активен {w['active_days']} дней из {DAYS_IN_APRIL}"
        used.add(w["user_id"])

    # 6. Highest passed-day ratio (≥50%, ≥3 active days)
    cands = [
        s for s in stats.values()
        if s["user_id"] not in used and s["active_days"] >= 3
    ]
    if cands:
        w = max(cands, key=lambda s: s["passed_days"] / s["active_days"])
        ratio = w["passed_days"] / w["active_days"]
        if ratio >= 0.5:
            facts[w["user_id"]] = (
                f"в {int(round(ratio * 100))}% активных дней добивал до нормы"
            )
            used.add(w["user_id"])

    # 7. Fallback: total + active days + avg/day
    for uid, s in stats.items():
        if uid in used:
            continue
        avg = s["total"] / DAYS_IN_APRIL
        facts[uid] = (
            f"{s['total']} кружков за {s['active_days']} активных дней "
            f"(~{avg:.1f}/день)"
        )

    return facts


def render(stats, facts, all_users):
    lines = ["🏁 <b>АПРЕЛЬСКИЙ ЧЕЛЛЕНДЖ — ИТОГИ</b>", ""]

    ranked = sorted(stats.values(), key=lambda s: s["total"], reverse=True)

    if ranked:
        lines.append("📊 рейтинг по кружкам:")
        lines.append("")
        for i, s in enumerate(ranked):
            avg = s["total"] / DAYS_IN_APRIL
            medal = MEDALS[i] if i < 3 else f"{i + 1}."
            streak_part = (
                f"  [рекорд стрика {s['best_streak']} 🔥]"
                if s["best_streak"] > 0 else ""
            )
            lines.append(
                f"{medal} {s['name']} — {s['total']} ({avg:.1f}/день){streak_part}"
            )
        lines.append("")

    if facts:
        lines.append("✨ интересное:")
        lines.append("")
        for s in ranked:
            f = facts.get(s["user_id"])
            if f:
                lines.append(f"• {s['name']} — {f}")
        lines.append("")

    no_show = [u for uid, u in all_users.items() if uid not in stats]
    if no_show:
        lines.append("😴 в апреле не записывали:")
        for u in no_show:
            lines.append(f"• {display_name(u)}")
        lines.append("")

    lines.append("———")
    lines.append("")
    lines.append(
        "Спасибо всем, кто согласился принять участие в апрельском челлендже. "
        "Бот берёт паузу до тех пор, пока кто-то из участников не вызовется "
        "проверить вас на стойкость и дисциплину."
    )
    return "\n".join(lines)


async def send_to_chat(text: str) -> None:
    req = HTTPXRequest(
        connect_timeout=20.0, read_timeout=20.0, write_timeout=20.0, pool_timeout=20.0
    )
    bot = Bot(token=BOT_TOKEN, request=req)
    async with bot:
        await _send_with_retry(bot, chat_id=CHAT_ID, text=text, parse_mode=ParseMode.HTML)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="actually post to chat")
    args = parser.parse_args()

    users, notes, streaks = fetch()
    stats = compute_stats(users, notes, streaks)
    facts = assign_facts(stats)
    text = render(stats, facts, users)

    print("=" * 60)
    print(text)
    print("=" * 60)
    print(f"\nLength: {len(text)} chars")

    if args.send:
        print("\n[sending to chat...]")
        asyncio.run(send_to_chat(text))
        print("OK — posted")
    else:
        print("\n(dry-run — use --send to actually post)")


if __name__ == "__main__":
    main()
