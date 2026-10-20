#!/usr/bin/env python3
"""notify_operator.py — единственный канал от агентов к оператору.

Правило, закреплённое в SOUL лидера: писать ТОЛЬКО когда
  (а) пришли деньги — с tx hash, или
  (б) требуется действие оператора.
Отчёты о прогрессе не отправляются.

Использование (из агента):
    python3 notify_operator.py --earned "0.0108 ETH получено, tx 0xabc…, баунти 1495"
    python3 notify_operator.py --need "Войди в X под аккаунтом @italeeex, окно открыто"

Отправка идёт через `hermes send -t telegram` — бот основного профиля,
домашний канал берётся из ~/.hermes/.env. Дубликаты подавляются: один и тот же
текст в течение часа повторно не уходит.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

STATE = Path("/home/asd/.hermes/cache/notify_operator_state.json")
DEDUP_HOURS = 1.0


def already_sent(text: str) -> bool:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    key = hashlib.sha1(text.encode("utf-8")).hexdigest()
    last = state.get(key, 0)
    return (time.time() - last) < DEDUP_HOURS * 3600


def mark_sent(text: str) -> None:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    state[hashlib.sha1(text.encode("utf-8")).hexdigest()] = time.time()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def send(text: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["hermes", "send", "-t", "telegram", text],
                           capture_output=True, text=True, timeout=90)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--earned", metavar="TEXT", help="деньги пришли (обязательно tx hash)")
    group.add_argument("--need", metavar="TEXT", help="нужно действие оператора")
    ap.add_argument("--no-dedup", action="store_true")
    a = ap.parse_args()

    if a.earned:
        text = "💰 " + a.earned.strip()
        if "tx" not in text.lower() and "0x" not in text:
            print("ВНИМАНИЕ: в сообщении о деньгах нет tx hash — такое доказывать нечем",
                  file=sys.stderr)
    else:
        text = "❗ " + a.need.strip()

    if not a.no_dedup and already_sent(text):
        print("дубль подавлен (тот же текст уже уходил в течение часа)")
        return 0

    code, out = send(text)
    print(out[:400])
    if code == 0:
        mark_sent(text)
        print("отправлено оператору")
    else:
        print("ОШИБКА ОТПРАВКИ", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
