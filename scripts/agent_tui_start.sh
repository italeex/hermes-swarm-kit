#!/bin/bash
# agent-tui — терминальный интерфейс управления агентами в tmux.
# Запуск:  bash /home/asd/.hermes/scripts/agent_tui_start.sh
# Мышь в tmux включена, окно 200x50, аттач по имени сессии.
set -u
SESSION="hermes-agents"
PROJ="${1:-}"

tmux kill-session -t "$SESSION" 2>/dev/null

if [ -n "$PROJ" ]; then
  tmux new-session -d -s "$SESSION" -x 200 -y 50 \
    "/usr/bin/python3 /home/asd/.hermes/scripts/agent_tui.py --project '$PROJ'"
else
  tmux new-session -d -s "$SESSION" -x 200 -y 50 \
    "/usr/bin/python3 /home/asd/.hermes/scripts/agent_tui.py"
fi

tmux set-option -t "$SESSION" mouse on >/dev/null 2>&1
tmux set-option -t "$SESSION" status off >/dev/null 2>&1
tmux set-option -t "$SESSION" history-limit 5000 >/dev/null 2>&1

echo "сессия tmux: $SESSION"
echo "подключиться:  tmux attach -t $SESSION"
