# TG push-ups bot

Telegram-бот для чата с физ-активностями (кружки: подтягивания, отжимания, приседания, планка).
Каждый день в 00:00 по локальному времени публикует сводку: кто прошёл дневную норму (≥4 кружка),
считает текущий стрик / рекорд / общее количество кружков у каждого.

## Стек

- Python 3.11+
- `python-telegram-bot` (polling + встроенный job queue)
- SQLite
- `Telethon` — только для разового бэкфилла истории

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить BOT_TOKEN и CHAT_ID
python bot.py
```

## Команды в чате

- `/stats` — твоя статистика (сегодня, всего, стрик)
- `/top` — таблица участников по стрикам

Кружки детектятся автоматически — бот просто слушает `video_note` в заданном `CHAT_ID`.

## Как узнать CHAT_ID

Добавь бота в чат, напиши что-нибудь, открой `https://api.telegram.org/bot<TOKEN>/getUpdates` —
там будет `chat.id` (для супергрупп отрицательный, вида `-100...`).

## Бэкфилл истории с 1 апреля

Bot API не видит сообщения до своего запуска. Для истории используется Telethon (юзер-клиент).

1. Получи `api_id` / `api_hash` на https://my.telegram.org → API development tools.
2. Впиши в `.env`: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `BACKFILL_SINCE=2026-04-01`.
3. Запусти `python backfill.py` — при первом запуске Telegram пришлёт код, нужно будет ввести.
4. Сессия сохранится в `backfill.session` — больше кодов не понадобится.

После бэкфилла обычный `bot.py` продолжит считать кружки в реальном времени.

## Деплой на VPS (systemd)

`/etc/systemd/system/pushups-bot.service`:

```ini
[Unit]
Description=TG push-ups bot
After=network-online.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/tg-pushups-bot
ExecStart=/home/botuser/tg-pushups-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pushups-bot
journalctl -u pushups-bot -f
```

## Структура

```
bot.py          — точка входа: listener + ежедневный job
handlers.py     — обработчики video_note и команд /stats, /top
scheduler.py    — построение и отправка дневной сводки
db.py           — SQLite: users, video_notes, streaks
config.py       — загрузка .env
backfill.py     — Telethon-скрипт, разовый импорт истории
```
