#!/bin/bash
# move_to_data.sh — перенос данных с корневого диска (/) на большой диск (/mnt/hermes_data).
#
# Схема: каталог переносится на /mnt/hermes_data, на старом месте остаётся симлинк.
# Так ничего не ломается: пути в конфигах, в systemd-юнитах и в скриптах остаются
# прежними, а данные физически лежат на диске 50 ГБ.
#
# Использование:
#   bash move_to_data.sh <путь-источник> [путь-назначения-внутри-/mnt/hermes_data]
#
# Пример:
#   bash move_to_data.sh /home/asd/.hermes/tools
#   bash move_to_data.sh /home/asd/.cache/ms-playwright

set -euo pipefail

DATA_ROOT=/mnt/hermes_data
SRC="$1"
DST_SUB="${2:-}"

if [ -z "$SRC" ]; then
  echo "нужен путь-источник" >&2
  exit 1
fi
if [ ! -e "$SRC" ]; then
  echo "нет такого пути: $SRC" >&2
  exit 1
fi
if [ -L "$SRC" ]; then
  echo "уже симлинк: $SRC -> $(readlink "$SRC")" >&2
  exit 0
fi

if [ -z "$DST_SUB" ]; then
  # сохраняем путь относительно корня: /home/asd/.hermes/tools -> home/asd/.hermes/tools
  DST="$DATA_ROOT${SRC}"
else
  DST="$DATA_ROOT/$DST_SUB"
fi

# не переносим внутрь самого себя
case "$DST" in
  "$SRC"/*) echo "назначение внутри источника" >&2; exit 1 ;;
esac

echo "источник: $SRC"
echo "назначение: $DST"

mkdir -p "$(dirname "$DST")"
if [ -e "$DST" ]; then
  echo "назначение уже существует: $DST" >&2
  exit 1
fi

# копируем с сохранением прав, затем проверяем, удаляем оригинал, ставим симлинк
rsync -a --info=progress2 "$SRC/" "$DST/"

echo "проверяю размер"
SRC_SIZE=$(du -sb "$SRC" | cut -f1)
DST_SIZE=$(du -sb "$DST" | cut -f1)
echo "источник: $SRC_SIZE байт, копия: $DST_SIZE байт"
if [ "$DST_SIZE" -lt $((SRC_SIZE * 95 / 100)) ]; then
  echo "КОПИЯ НЕПОЛНАЯ — оригинал оставлен на месте" >&2
  exit 1
fi

rm -rf "$SRC" 2>/dev/null || true
# Go-module cache и часть npm-кешей хранят файлы в режиме 0444 — rsync переносит
# эти права, и rm без прав не может их удалить. Снимаем read-only перед удалением.
chmod -R u+w "$SRC" 2>/dev/null || true
rm -rf "$SRC"
ln -s "$DST" "$SRC"
echo "готово: $SRC -> $DST"
df -h / "$DATA_ROOT" | tail -2
