#!/usr/bin/env python3
"""nudge.py — подталкивание команд к заработку.

Раз в N минут смотрит оба проекта Agora и, если команда молчит или буксует,
отправляет в командный канал короткое указание. Это «попеременная рука»:
агент получает толчок сам, без участия оператора.

Что считается буксовсом:
  - в канале нет сообщений дольше порога;
  - нет задач в работе, но есть задачи в очереди или готовые к проверке;
  - все задачи заблокированы.

Указание всегда конкретное: что именно делать сейчас и что считается результатом.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

KANBAN_DB = Path.home() / ".hermes" / "kanban.db"
STATE = Path("/home/asd/.hermes/cache/nudge_state.json")
SILENCE_MIN = 25          # сколько минут тишины считается застой
IDLE_TASK_MIN = 8         # сколько минут без задач в работе


def db():
    con = sqlite3.connect(f"file:{KANBAN_DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def project_state(project: str) -> dict:
    con = db()
    try:
        root = con.execute(
            "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
            (f"agora-{project}",)).fetchone()
        if root is None:
            return {"ok": False, "why": "канала нет"}
        root_id = root[0]
        counts = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE tenant = ? AND status != 'archived' GROUP BY status",
            (f"agora-{project}",))}
        last_msg = con.execute(
            "SELECT MAX(created_at) FROM task_comments WHERE task_id = ?", (root_id,)).fetchone()[0] or 0
        last_task = con.execute(
            "SELECT MAX(started_at) FROM tasks WHERE tenant = ? AND status = 'running'",
            (f"agora-{project}",)).fetchone()[0] or 0
        blocked = con.execute(
            "SELECT title, assignee FROM tasks WHERE tenant = ? AND status = 'blocked' LIMIT 3",
            (f"agora-{project},",)).fetchall() if False else con.execute(
            "SELECT title, assignee FROM tasks WHERE tenant = ? AND status = 'blocked' LIMIT 3",
            (f"agora-{project}",)).fetchall()
    finally:
        con.close()
    return {"ok": True, "channel": root_id, "counts": counts,
            "last_msg": last_msg, "last_task": last_task,
            "blocked": [{"title": r["title"], "assignee": r["assignee"]} for r in blocked]}


def send(project: str, text: str) -> bool:
    con = sqlite3.connect(KANBAN_DB, timeout=15)
    try:
        row = con.execute(
            "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
            (f"agora-{project}",)).fetchone()
        if row is None:
            return False
        payload = json.dumps({"type": "mention", "author": "оператор",
                              "content": text, "target": "leader"}, ensure_ascii=False)
        con.execute("INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
                    (row[0], "оператор", "[agora:msg] " + payload, time.time()))
        con.commit()
    finally:
        con.close()
    try:
        subprocess.Popen(["hermes", "cron", "run", f"heartbeat-{project}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return True


PROMPTS = {
    "crypto-earn": [
        "Толчок. Цель проекта — деньги, а не отчёт. Сейчас главный вопрос: есть ли ещё один канал, "
        "кроме POIDH, где платят в крипту без гейта и без человека? Проверь один канал прямо сейчас: "
        "живой запрос, сумма, как платят, что надо сдать. Если канал мёртв — закрой его с доказательством "
        "и пиши в журнал. Если живой — подай заявку сегодня, с tx hash. Одно действие за этот heartbeat.",
        "Толчок. Заявка на 1495 подана, дальше ждём голосование. Не жди: возьми следующий кандидат из "
        "реестра и доведи его до проверяемой заявки. Покажи в канале: ссылка, сумма, что сдаём, как платят, "
        "и ссылку на живое доказательство рельса.",
        "Толчок. Если всё, что можно подать, подано — пиши отчёт о деньгах: сколько подтверждено, "
        "сколько ожидается, что блокирует. И предложи лидеру новый канал заработка, который ещё не проверяли. "
        "Одно действие за этот heartbeat.",
    ],
    "demo-sites": [
        "Толчок. Страницы почти готовы — их нужно не доводить, а продавать. Возьми проверенные лиды "
        "и отправь первую волну писем: у каждого ссылка на демо и один измеренный дефект. Результат — "
        "число отправленных писем в журнале, а не отчёт о вёрстке.",
        "Толчок. Проверь ответы на отправленные письма. Есть ответ — отвечай в течение часа, "
        "пока интерес жив. Нет ответов — расширь базу лидов и готовь вторую волну. Результат этого "
        "heartbeat: либо новый ответ, либо новая партия проверенных лидов.",
        "Толчок. Считай деньги, а не задачи: сколько писем ушло, сколько ответов, сколько демо показано, "
        "сколько оплат. Если оплат нет — сформулируй, что именно в предложении не работает, и поменяй "
        "в письме одно конкретное место. Одно изменение, одно действие.",
    ],
}


def main() -> int:
    now = time.time()
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    projects = sys.argv[1:] or list(PROMPTS)
    acted = []
    for project in projects:
        st = project_state(project)
        if not st.get("ok"):
            continue
        counts = st["counts"]
        silence_min = (now - (st["last_msg"] or 0)) / 60
        idle_min = (now - (st["last_task"] or 0)) / 60
        running = counts.get("running", 0)
        queued = counts.get("todo", 0) + counts.get("ready", 0)
        blocked = counts.get("blocked", 0)
        prev = state.get(project, {})
        prompt_index = prev.get("prompt_index", 0)

        need = False
        reason = ""
        if silence_min > SILENCE_MIN:
            need = True
            reason = f"тишина {int(silence_min)} мин"
        elif running == 0 and (queued > 0 or blocked > 0) and idle_min > IDLE_TASK_MIN:
            need = True
            reason = f"нет задач в работе, в очереди {queued}, в блоке {blocked}"
        if not need:
            continue
        # не тыкать чаще, чем раз в 12 минут в один проект
        if now - prev.get("last_nudge", 0) < 12 * 60:
            continue
        text = PROMPTS.get(project, PROMPTS["crypto-earn"])[prompt_index % len(PROMPTS.get(project, PROMPTS["crypto-earn"]))]
        if send(project, text):
            state[project] = {"last_nudge": now, "prompt_index": prompt_index + 1,
                              "reason": reason}
            acted.append(f"{project}: {reason}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    if acted:
        print("толчки отправлены:", "; ".join(acted))
    else:
        print("толчки не нужны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
