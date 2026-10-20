#!/bin/bash
# nudge.sh — cron-обёртка: подталкивает команды Agora к заработку.
set -u
LOG=/mnt/hermes_data/work/nudge.log
{
  echo "=== $(date -Is) ==="
  /usr/bin/python3 /home/asd/.hermes/scripts/nudge.py "$@"
} >> "$LOG" 2>&1
