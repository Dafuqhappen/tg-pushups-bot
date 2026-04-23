# TG push-ups bot

Telegram-бот для чата с физ-активностями (кружки = video-notes: подтягивания, отжимания, приседания, планка). Считает кружки по каждому участнику, ведёт стрики, каждое утро публикует сводку за прошедший день и дважды ещё в течение дня отправляет цитаты-пинки.

## Что делает

- Слушает `video_note` в заданном чате и автоматически их считает (пересланные тоже).
- Ведёт «день» с 09:00 до 09:00 следующего дня (настраивается через `DAY_CUTOFF_HOUR`) — потому что кружки часто прилетают после полуночи и календарный день бы рвался.
- Три ежедневные рассылки в чат:
  - **09:00** — сводка за только что закончившийся день + мотивационная цитата.
  - **15:00** — `bros`-цитата в духе *«bros, нужно выполнить норму, иначе…»*.
  - **21:00** — ещё одна мотивационная цитата.
- Цитаты из двух независимых пулов не повторяются в рамках цикла — пул сбрасывается только после того, как все его цитаты успели прозвучать.
- В сводке у тех, кто прошёл норму, выводится текущий стрик, рекордный стрик и общее число кружков. Тех, кто сделал 1/2/3 из 4, показывает отдельным списком с градированной подписью (25% / 50% / 75% / 100%).
- Ретраи на сетевые таймауты в запланированных рассылках — одиночный `ConnectTimeout` к `api.telegram.org` не приводит к потере сообщения.

## Стек

- Python 3.11+
- `python-telegram-bot[job-queue]` (polling + APScheduler)
- SQLite
- `Telethon` — только для разового бэкфилла истории (Bot API не видит сообщения до запуска бота)

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить BOT_TOKEN и CHAT_ID, остальное опционально
python bot.py
```

## Конфиг (`.env`)

| Ключ | По умолчанию | Описание |
|------|--------------|----------|
| `BOT_TOKEN` | — (required) | Токен бота из @BotFather |
| `CHAT_ID` | — (required) | ID чата/супергруппы (отрицательный, `-100...`) |
| `TIMEZONE` | `Europe/Moscow` | Часовой пояс для расписаний и границ дня |
| `DAILY_GOAL` | `4` | Сколько кружков = норма за день |
| `DB_PATH` | `data/pushups.db` | Путь к SQLite-файлу |
| `DAY_CUTOFF_HOUR` | `9` | Час, в который кончается логический день и стартует следующий |
| `TG_API_ID` / `TG_API_HASH` / `TG_PHONE` | — | Для бэкфилла (см. ниже) |
| `BACKFILL_SINCE` | `2026-04-01` | С какой даты бэкфиллить историю |

`BOT_TOKEN` обязан быть доступен только процессу бота. Токены в публичном репо не хранятся и не коммитятся — для этого в `.gitignore` прописаны `.env`, `*.session`, `*.db` и `data/`.

## Как узнать `CHAT_ID`

Добавь бота в чат, напиши в чат что-нибудь, открой в браузере:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Берёшь `result[*].message.chat.id` — для супергрупп он будет вида `-100...`.

У бота в @BotFather должен быть выключен privacy-mode (`/setprivacy → Disable`), иначе он не видит обычные сообщения в группе.

## Команды в чате

- `/stats` — твоя статистика (сегодня, всего, текущий стрик, рекорд).
- `/top` — таблица участников по стрикам.

## Бэкфилл истории

Bot API не видит сообщения, отправленные до запуска бота. Если надо учесть уже накопившиеся кружки — пригоняется Telethon под твоим юзер-аккаунтом.

1. Получи `api_id` / `api_hash` на <https://my.telegram.org> → API development tools.
2. Впиши в `.env`: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `BACKFILL_SINCE=YYYY-MM-DD`.
3. `python backfill.py` — при первом запуске Telegram пришлёт код, введёшь в терминал. Сессия сохранится в `backfill.session` (в `.gitignore`) — код потом не понадобится.
4. После бэкфилла прогнать `python recount_streaks.py` — он пересчитает стрики с нуля по имеющейся истории.

> **Нюанс:** Telethon под юзер-аккаунтом возвращает `first_name` с точки зрения вызывающего — то есть твои **контактные лейблы**, а не profile first_name, выставленный самим человеком. Поэтому `backfill.py` вызывает `db.upsert_user(..., update_first_name=False)` — имена уже существующих юзеров он не перезатирает. Бот, работающий через Bot API, при каждом новом кружке подтягивает настоящий profile first_name.

## Утилиты

- `preview_summary.py [YYYY-MM-DD]` — печатает, как выглядел бы 09:00 / 15:00 / 21:00 пост за указанный день, ничего при этом не отправляя. Без аргумента — за вчера.
- `recount_streaks.py` — пересчитывает стрики во всей БД с нуля (идёт по дням от `BACKFILL_SINCE` до вчерашнего). Безопасно запускать повторно.

## Деплой на VPS (systemd, user-scope)

Бот гоняется под обычным юзером, без root. На friend-сервере это изолирует его от остальной системы и не требует `sudo` для обновлений.

На сервере:

```bash
git clone https://github.com/<you>/tg-pushups-bot.git ~/tg-pushups-bot
cd ~/tg-pushups-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env     # заполнить
loginctl enable-linger $USER   # чтобы юнит пережил logout/reboot (нужен sudo разово)
```

`~/.config/systemd/user/pushups-bot.service`:

```ini
[Unit]
Description=TG push-ups bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/tg-pushups-bot
ExecStart=%h/tg-pushups-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5

# hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/tg-pushups-bot
PrivateTmp=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=256M

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now pushups-bot
systemctl --user status pushups-bot
journalctl --user -u pushups-bot -f
```

## Структура

```
bot.py              — точка входа: handlers + три джобы (09:00/15:00/21:00)
handlers.py         — обработчик video_note и команд /stats, /top
scheduler.py        — построение сводки + рассылки с ретраями на TimedOut
quotes.py           — пулы цитат (MOTIVATIONAL, BROS) + не-повторяющийся выбор
db.py               — SQLite: users, video_notes, streaks, used_quotes
config.py           — .env + хелперы для «логического дня» с кат-офом в 09:00
backfill.py         — разовый Telethon-импорт истории чата
recount_streaks.py  — разовый пересчёт стриков по имеющейся БД
preview_summary.py  — офлайн-превью дневной сводки
```
