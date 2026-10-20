#!/bin/bash
# data_disk_layout.sh — раскладка и проверка дисков.
#
# На этой машине два диска:
#   /dev/sda2  25 ГБ  -> /            (система, ядро Hermes, мелкие файлы)
#   /dev/sdb   50 ГБ  -> /mnt/hermes_data  (данные: профили, инструменты, работа)
#
# Правило: на корне остаётся только то, что должно быть рядом с системой и
# меняется часто. Всё, что растёт и накапливается, живёт на /mnt/hermes_data.
# Крупные каталоги переносятся скриптом move_to_data.sh: на старом месте
# остаётся симлинк, поэтому пути в конфигах и юнитах не меняются.

set -u
DATA=/mnt/hermes_data

echo "=== диски ==="
df -h / "$DATA" | tail -2

echo
echo "=== что на корне (/) ==="
du -shx /home/asd/.hermes/* 2>/dev/null | sort -rh | head -8
du -shx /home/asd/* 2>/dev/null | sort -rh | head -6

echo
echo "=== что на диске данных ($DATA) ==="
du -shx "$DATA"/* 2>/dev/null | sort -rh | head -12

echo
echo "=== перенесённые каталоги (симлинки) ==="
for d in /home/asd/.hermes/tools /home/asd/.hermes/profiles /home/asd/.hermes/cache \
         /home/asd/.hermes/chrome-debug /home/asd/.hermes/hermes-agent/node_modules \
         /home/asd/.hermes/hermes-agent/apps /home/asd/ai_agent_project /home/asd/hermes_swarm \
         /home/asd/go /home/asd/w165 /home/asd/reports /home/asd/agentstack; do
  if [ -L "$d" ]; then
    printf "  %-48s -> %s\n" "$d" "$(readlink "$d")"
  fi
done

echo
echo "=== крупнейшие файлы на диске данных (>150 МБ) ==="
find "$DATA" -xdev -type f -size +150M -printf "%s %p\n" 2>/dev/null | sort -rn | head -8 \
  | awk '{printf "  %.0f MB %s\n", $1/1048576, $2}'

echo
echo "=== живые процессы, удерживающие удалённые файлы ==="
sudo -n lsof -nP 2>/dev/null | awk '$7 ~ /^[0-9]+$/ && /deleted/ {print $7, $1, $2}' | sort -rn | head -5 \
  || echo "  (lsof недоступен или таких файлов нет)"
