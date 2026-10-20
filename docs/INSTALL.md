# Установка Hermes Swarm Kit

Проверено на Ubuntu 24.04, Hermes 0.21+, Python 3.12+.

## 0. Предусловия

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes agora setup            # разворачивает скиллы Agora в skills/collaboration
hermes gateway restart
```

Проверка: `hermes plugins list | grep agora`.

## 1. Плагин изменения Hermes (hermes-ops)

```bash
cp -r plugins/hermes-ops ~/.hermes/plugins/
hermes plugins enable hermes-ops
hermes tools enable hermes_ops --platform cli
```

Инструменты появляются в **следующей сессии** — плагин с `provides_tools`
регистрируется при старте процесса.

Чтобы агенты тоже получили инструмент, в `config.yaml` каждого профиля
должно быть:

```yaml
platform_toolsets:
  cli:
  - file
  - web
  - skills
  - todo
  - session_search
  - hermes_ops
```

И в корневом `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - agora
    - hermes-ops
    - agent-board
platform_toolsets:
  cli: [..., hermes_ops]
```

## 2. Вкладка «Агенты» в дашборде (agent-board)

```bash
cp -r plugins/agent-board ~/.hermes/plugins/
hermes plugins enable agent-board
hermes dashboard --port 9119 --no-open
```

Вкладка появится рядом с Kanban: **http://127.0.0.1:9119/agents**.

Структура плагина:
```
plugins/agent-board/
  plugin.yaml                    # манифест плагина (name, provides_tools)
  dashboard/manifest.json        # вкладка дашборда: path, entry, api
  dashboard/dist/index.js        # фронтенд на Plugin SDK (React берётся из дашборда)
  dashboard/plugin_api.py        # API: /api/plugins/agent-board/...
```

Проверка, что API жив: `curl -s http://127.0.0.1:9119/api/plugins/agent-board/projects`.

## 3. Терминальный интерфейс

```bash
mkdir -p ~/.hermes/scripts
cp scripts/agent_tui.py scripts/agent_tui_start.sh scripts/make_role.py ~/.hermes/scripts/
bash ~/.hermes/scripts/agent_tui_start.sh demo-sites
tmux attach -t hermes-agents
```

Как сервис:

```ini
# ~/.config/systemd/user/agent-tui.service
[Unit]
Description=Hermes TUI для управления агентами
After=network-online.target hermes-gateway.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash /home/asd/.hermes/scripts/agent_tui_start.sh demo-sites
ExecStop=/usr/bin/tmux kill-session -t hermes-agents
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now agent-tui.service
```

## 4. Библиотека ролей

```bash
cp scripts/make_role.py ~/.hermes/scripts/
python3 ~/.hermes/scripts/make_role.py list
python3 ~/.hermes/scripts/make_role.py install leads --team site-factory --project demo-sites
```

## 5. Структура vault

```bash
mkdir -p ~/ai_agent_project/vault/Агенты/{Предложения}
```

| Файл | Назначение |
|---|---|
| `Правила.md` | жёсткие правила: деньги, правда, журнал |
| `Полезное.md` | эндпоинты, команды, грабли |
| `Журнал - <проект>.md` | хронология проекта |
| `Предложения/*.json` | заявки на скиллы и cron |
| `Операции.md` | журнал операций `hermes-ops` |
| `Деньги.json` | реестр подтверждённых выплат |

## 6. Правки в Agora (если ставите с нуля)

Файл `~/.hermes/plugins/agora/agora/worker_templates.py`:
- добавить роль `sourcer` (ключ в `TEMPLATES`, `soul_template`, `toolsets`).

Файл `~/.hermes/plugins/agora/agora/team_manager.py`:
- добавить функцию `add_worker_to_team(team_name, worker_name, project=None)`.

Файл `~/.hermes/plugins/agora/tools/__init__.py`:
- добавить инструмент `agora_hire_worker` (схема `_HIRE_WORKER_SCHEMA`, обработчик,
  `ctx.register_tool`).

Файл `~/.hermes/plugins/agora/agora/leader_loop.py`:
- в `_HEARTBEAT_PROMPT` добавить блок про найм и про гейт на скиллы/cron.

Готовые патчи лежат в `scripts/agora_worker_templates_patched.py` (эталон роли
`sourcer`) и описаны в `docs/roles.md`.

## 7. Проверка

```bash
hermes plugins list | grep -E "agora|hermes-ops|agent-board"
hermes tools list | grep hermes_ops
tmux ls | grep hermes-agents
hermes kanban list
hermes agora stats
```
