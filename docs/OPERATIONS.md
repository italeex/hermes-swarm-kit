# Операции

## TUI

```bash
bash ~/.hermes/scripts/agent_tui_start.sh demo-sites   # запуск
tmux attach -t hermes-agents                           # подключение
tmux kill-session -t hermes-agents                     # закрыть
```

Живёт как systemd-юнит `agent-tui.service` (автозапуск, переживает перезагрузку).

**Ловушка curses:** `stdscr.box(stdscr, 0, 0)` не работает — у `_curses.window.box`
другая сигнатура. Рамка рисуется линиями `addnstr` в `try/except`: на краю экрана
`addnstr` бросает `curses.error`.

**Ловушка tmux:** сессия, запущенная из скрипта без `setsid`, умирает вместе
с вызывающим процессом. systemd-юнит с `RemainAfterExit=yes` надёжнее.

## Ключи провайдера

Ключ `OPENCODE_GO_API_KEY` лежит в `~/.hermes/.env` и **в каждом профиле агента**
(`~/.hermes/profiles/<имя>/.env`). Новый профиль получает копию корневого `.env`
при создании, поэтому после смены ключа его надо раздать во все профили:

```python
import pathlib, hashlib
key = next(l.split("=",1)[1].strip().strip('"')
           for l in pathlib.Path.home().joinpath(".hermes/.env").read_text().splitlines()
           if l.startswith("OPENCODE_GO_API_KEY="))
for p in pathlib.Path.home().joinpath(".hermes/profiles").iterdir():
    env = p / ".env"
    if not env.is_file(): continue
    out = []
    for l in env.read_text(encoding="utf-8").splitlines(True):
        out.append("OPENCODE_GO_API_KEY=" + key + "\n" if l.startswith("OPENCODE_GO_API_KEY=") else l)
    env.write_text("".join(out), encoding="utf-8"); env.chmod(0o600)
```

Проверка ключа живым запросом (нужен заголовок `x-opencode-session`, иначе API отвечает 400):

```bash
curl -s --proxy http://127.0.0.1:12334 -X POST "https://opencode.ai/zen/go/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "x-opencode-session: check" \
  -d '{"model":"minimax-m3.1-flash-free","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'
```

После смены ключа перезапустите: `hermes gateway restart`, `hermes dashboard restart`,
и воркеров (`pkill -f "hermes -p "`), затем `hermes cron run heartbeat-<проект>`.

## Диск

Дом `/` на этой машине — 25 ГБ, и он заполнялся до 96 %. Что помогло:

| Что | Освободил | Безопасно? |
|---|---|---|
| `hermes sessions prune --source subagent --older-than 7d --yes --force` | ~1 ГБ | да, это машинные транскрипты |
| `VACUUM INTO` в `/mnt` + симлинк на `state.db` | ~700 МБ | да, старый файл уходит в `/mnt` |
| `rm -rf /mnt/hermes_data/npmcache` | 1.4 ГБ | да, восстановится сам |
| `rm -rf /home/asd/.hermes/cache/uv` | 301 МБ | да, кэш пакетов |
| `rm -rf /home/asd/.cache/ms-playwright-mcp` | 51 МБ | да |
| базы закрытых исследований в `/mnt` | 8.6 ГБ | да, это мёртвые проекты |

**Нельзя трогать:** `~/.hermes/chrome-debug` и `~/.hermes/chrome-gmail` (живые логины),
`~/.cache/ms-playwright/chromium-1243` (держат живые мосты браузера),
`~/.cache/mozilla` (внутри — не только кэш), `.env` профилей.

**VACUUM на месте требует свободного места, равного итоговому размеру.** Поэтому
компакт собирается в `/mnt` (`VACUUM INTO`), а `state.db` заменяется симлинком.
Скрипт `swap_state_db.sh` делает это сам, когда сессия Hermes закрыта.

## Cron

| Задача | Расписание | Что делает |
|---|---|---|
| `heartbeat-<проект>` | 15–20 мин | будит лидера проекта |
| `gmail-replies` | 15 мин | смотрит ответы на рассылку |
| `outreach-daily` | 10:00 | сводка по отправленным |
| `outreach-followups` | 11:00 | напоминания через 3 дня |
| `disk-guard` | 60 мин | чистка диска по расписанию |

Проверить: `hermes cron list`, `hermes cron runs <имя>`, `hermes cron run <имя>`.
Бывает, что `runs` показывает «No cron execution attempts recorded» при успешных
запусках — тогда смотрите лог задачи, а не историю.

## Журналы

| Файл | Что пишется |
|---|---|
| `vault/Агенты/Журнал - Крипта.md` | хронология крипто-команды |
| `vault/Агенты/Журнал - Сайты.md` | хронология сайтов |
| `vault/Агенты/Полезное.md` | эндпоинты, команды, грабли |
| `vault/Агенты/Правила.md` | жёсткие правила (деньги, правда, журнал) |
| `vault/Агенты/Предложения/` | JSON-заявки на скиллы и cron |
| `vault/Агенты/Операции.md` | все операции `hermes-ops` |
| `vault/Агенты/Деньги.json` | подтверждённые выплаты |

Формат записи в журнал: `## ГГГГ-ММ-ДД ЧЧ:ММ — что сделано`, ниже 2–5 строк:
результат, чем подтверждено (команда и вывод), что дальше.

## Проверка живости

```bash
hermes gateway status                  # шлюг
hermes plugins list                    # плагины
hermes profile list                    # профили
hermes kanban list                     # задачи
hermes agora stats                     # обсуждения
df -h / /mnt/hermes_data                # диск
systemctl --user list-units --no-pager | grep hermes
```

## Аппаратный лимит

RAM 16 ГБ без свопа. Семь-девять одновременно работающих профилей — это граница:
при нехватке памяти падают и воркеры, и gateway. Расписание heartbeat'ов лучше
разводить по времени, а не запускать одновременно.
