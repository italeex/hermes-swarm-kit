#!/usr/bin/env python3
"""agent_tui.py — терминальный интерфейс управления агентами.

Запуск:
    python3 agent_tui.py

Управление мышью и клавиатурой. Экраны: ДОСКА, АГЕНТЫ, ПЕРЕПИСКА, ПРЕДЛОЖЕНИЯ, ДЕНЬГИ.

Не «просто посмотреть»: с доски можно назначить, заблокировать, разблокировать,
закрыть, поднять задачу, разбудить лидера, утвердить или отклонить предложение
агента (создание скилла или cron-задачи).
"""
from __future__ import annotations

import argparse
import curses
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
HERMES = HOME / ".hermes"
KANBAN_DB = HERMES / "kanban.db"
VAULT = Path("/home/asd/ai_agent_project/vault/Агенты")
LEDGER = VAULT / "Деньги.json"
PROPOSALS = VAULT / "Предложения"
PLUGIN_DIR = HERMES / "plugins" / "agora"

STATUS_ORDER = ["running", "blocked", "ready", "todo", "done"]
STATUS_RU = {
    "running": "в работе", "blocked": "заблокирована", "ready": "готова к проверке",
    "todo": "в очереди", "done": "выполнена", "scheduled": "фон", "failed": "ошибка",
    "cancelled": "отменена",
}
STATUS_COLOR = {
    "running": 3, "blocked": 1, "ready": 4, "todo": 7, "done": 8,
    "scheduled": 5, "failed": 1, "cancelled": 8,
}
TASK_COLOR = {
    "running": 2, "blocked": 1, "ready": 4, "todo": 7, "done": 8,
    "scheduled": 5, "failed": 1, "cancelled": 8,
}
AGENT_STATUS_RU = {
    "running": "работает", "ready": "ждёт запуска", "blocked": "заблокирован", "idle": "свободен",
}


# ------------------------------------------------------------------ данные

def db():
    con = sqlite3.connect(f"file:{KANBAN_DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def agenda_roster(project: str) -> list[dict]:
    if not (PLUGIN_DIR / "agora").is_dir():
        return []
    import importlib
    import sys as _s
    import types
    if str(PLUGIN_DIR.parent) not in _s.path:
        _s.path.insert(0, str(PLUGIN_DIR.parent))
    ns = _s.modules.get("hermes_plugins")
    if ns is None:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        _s.modules["hermes_plugins"] = ns
    pkg = "hermes_plugins.agora"
    if pkg not in _s.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PLUGIN_DIR)]
        mod.__package__ = pkg
        _s.modules[pkg] = mod
    try:
        tm = importlib.import_module("hermes_plugins.agora.agora.team_manager")
        team = tm.get_team_for_project(project) or tm.get_team("site-factory")
        if not team:
            return []
        return [{"name": w["name"], "role": w.get("role", "")} for w in team.get("workers", [])]
    except Exception:
        return []


def load_state(project: str | None = None) -> dict:
    con = db()
    try:
        rows = con.execute(
            "SELECT id, title, status, assignee, tenant, created_at, completed_at, body, result "
            "FROM tasks WHERE status != 'archived' ORDER BY created_at DESC LIMIT 400"
        ).fetchall()
        projects = sorted({(r["tenant"] or "default").replace("agora-", "") for r in rows})
        tasks = []
        for r in rows:
            proj = (r["tenant"] or "default").replace("agora-", "")
            if project and proj != project:
                continue
            tasks.append({
                "id": r["id"], "title": (r["title"] or "").replace("[Motion] ", "").strip(),
                "status": r["status"] or "todo", "assignee": r["assignee"] or "",
                "project": proj, "created_at": r["created_at"],
                "completed_at": r["completed_at"], "body": r["body"] or "",
                "result": r["result"] or "",
            })
        ids = {t["id"] for t in tasks}
        parents: dict[str, list[str]] = {}
        for r in con.execute("SELECT parent_id, child_id FROM task_links"):
            if r["child_id"] in ids and r["parent_id"] in ids:
                parents.setdefault(r["child_id"], []).append(r["parent_id"])
        titles = {t["id"]: t["title"] for t in tasks}
        feed = []
        for r in con.execute("SELECT task_id, author, body, created_at FROM task_comments "
                             "ORDER BY created_at DESC LIMIT 200"):
            body = (r["body"] or "").strip()
            if not body:
                continue
            author = r["author"] or ""
            if body.startswith("[agora:msg]"):
                try:
                    payload = json.loads(body[len("[agora:msg]"):].strip())
                except ValueError:
                    continue
                author = payload.get("author") or author
                body = str(payload.get("content") or "")
            elif body.startswith("[agora:"):
                continue
            feed.append({"task_id": r["task_id"], "task_title": titles.get(r["task_id"], ""),
                         "author": author, "body": body, "ts": r["created_at"]})
        channel = None
        for r in con.execute("SELECT id, tenant FROM tasks WHERE status='scheduled'"):
            if (r["tenant"] or "").replace("agora-", "") == (project or ""):
                channel = r["id"]
                break
    finally:
        con.close()

    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(t["assignee"] or "без исполнителя", []).append(t)
    if project:
        for w in agenda_roster(project):
            groups.setdefault(w["name"], [])
    agents = []
    for name, items in groups.items():
        cur = [t for t in items if t["status"] in ("running", "blocked", "ready", "todo")]
        done = [t for t in items if t["status"] == "done"]
        cur.sort(key=lambda t: STATUS_ORDER.index(t["status"]) if t["status"] in STATUS_ORDER else 9)
        done.sort(key=lambda t: t["completed_at"] or 0, reverse=True)
        status = "idle"
        if any(t["status"] == "running" for t in items):
            status = "running"
        elif any(t["status"] == "blocked" for t in items):
            status = "blocked"
        elif any(t["status"] == "ready" for t in items):
            status = "ready"
        agents.append({"name": name, "status": status, "tasks": cur, "done": done,
                       "running": sum(1 for t in items if t["status"] == "running"),
                       "ready": sum(1 for t in items if t["status"] == "ready"),
                       "blocked": sum(1 for t in items if t["status"] == "blocked"),
                       "todo": sum(1 for t in items if t["status"] == "todo"),
                       "done_n": len(done)})
    agents.sort(key=lambda a: (-a["running"], a["name"]))
    return {"projects": projects, "tasks": tasks, "feed": feed, "agents": agents,
            "channel": channel}


def load_proposals() -> list[dict]:
    out = []
    if not PROPOSALS.is_dir():
        return out
    for f in sorted(PROPOSALS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        d["_file"] = str(f)
        d.setdefault("status", "pending")
        out.append(d)
    return out


def load_money() -> dict:
    if not LEDGER.exists():
        return {"items": [], "total_usd": 0.0}
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {"items": [], "total_usd": 0.0}


# ------------------------------------------------------------------ действия

def run_cli(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=90)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def kanban(action: str, task_id: str, *extra: str) -> tuple[int, str]:
    return run_cli(["hermes", "kanban", action, task_id, *extra])


def wake_leader(project: str) -> tuple[int, str]:
    return run_cli(["hermes", "cron", "run", f"heartbeat-{project}"])


def send_to_channel(project: str, text: str) -> tuple[int, str]:
    con = sqlite3.connect(KANBAN_DB, timeout=15)
    try:
        row = con.execute(
            "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
            (f"agora-{project}",)).fetchone()
        if row is None:
            return 1, "канал проекта не найден"
        payload = json.dumps({"type": "mention", "author": "оператор",
                              "content": text, "target": "leader"}, ensure_ascii=False)
        con.execute("INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
                    (row[0], "оператор", "[agora:msg] " + payload, time.time()))
        con.commit()
    finally:
        con.close()
    wake_leader(project)
    return 0, "доставлено, лидер разбужен"


def approve_proposal(prop: dict) -> tuple[int, str]:
    """Утвердить предложение: создать скилл или cron-задачу.

    Требуется согласование лидера: без "endorsed": true предложение не выполняется.
    """
    if not prop.get("endorsed"):
        return 1, "лидер не согласовал (нет endorsed). Попросите лидера рассмотреть."
    kind = prop.get("kind")
    path = pathlib.Path(prop["_file"])
    if kind == "skill":
        name = prop.get("name") or ""
        if not name:
            return 1, "в предложении нет имени скилла"
        if not all(ch.isalnum() or ch in "-_" for ch in name) or name.lower() != name:
            return 1, f"имя скилла '{name}' недопустимо: только строчные буквы, цифры, дефис"
        target = HERMES / "skills" / name
        if (target / "SKILL.md").exists():
            return 1, f"скилл {name} уже существует"
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(prop.get("skill_text", ""), encoding="utf-8")
        d = dict(prop)
        d["status"] = "approved"
        d["approved_at"] = time.time()
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0, f"скилл {name} создан"
    if kind == "cron":
        args = prop.get("cron_args") or []
        if not args:
            return 1, "в предложении нет команды cron"
        code, out = run_cli(["hermes", "cron", "create", *args])
        d = dict(prop)
        d["status"] = "approved" if code == 0 else "failed"
        d["cron_output"] = out[-800:]
        d["approved_at"] = time.time()
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return code, out[-400:]
    return 1, f"неизвестный тип предложения: {kind}"


def reject_proposal(prop: dict, reason: str) -> tuple[int, str]:
    path = pathlib.Path(prop["_file"])
    d = dict(prop)
    d["status"] = "rejected"
    d["reject_reason"] = reason
    d["rejected_at"] = time.time()
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0, "отклонено"


# ------------------------------------------------------------------ TUI

class Tui:
    def __init__(self, project: str | None = None):
        self.project = project
        self.screen_tab = 0
        self.tabs = ["ДОСКА", "АГЕНТЫ", "ПЕРЕПИСКА", "ПРЕДЛОЖЕНИЯ", "ДЕНЬГИ"]
        self.row = 0
        self.col = 0
        self.state = load_state(project)
        self.proposals = load_proposals()
        self.money = load_money()
        self.msg = ""
        self.msg_kind = 0
        self.input = ""
        self.input_mode = ""
        self.stdscr = None
        self.last_refresh = 0.0

    # ---- вспомогательное
    def notice(self, text: str, kind: int = 0):
        self.msg = text
        self.msg_kind = kind

    def refresh(self, force: bool = False):
        now = time.time()
        if not force and now - self.last_refresh < 3:
            return
        self.last_refresh = now
        self.state = load_state(self.project)
        self.proposals = load_proposals()
        self.money = load_money()

    def switch_project(self, idx: int):
        projects = self.state["projects"]
        if not projects:
            return
        self.project = projects[idx % len(projects)]
        self.row = 0
        self.refresh(force=True)
        self.notice(f"проект: {self.project}")

    def visible_tasks(self) -> list[dict]:
        tasks = self.state["tasks"]
        order = {s: i for i, s in enumerate(STATUS_ORDER)}
        return sorted(tasks, key=lambda t: (order.get(t["status"], 8), t["created_at"] or 0))

    # ---- экраны
    def draw_board(self, stdscr, h: int, w: int):
        tasks = self.visible_tasks()
        half = w // 2
        self._panel(stdscr, 0, 0, half, h, "ЗАДАЧИ")
        y = 1
        limit = h - 2
        for i, t in enumerate(tasks):
            if y >= limit:
                break
            sel = (i == self.row)
            attr = curses.A_REVERSE if sel else curses.A_NORMAL
            if not sel:
                attr |= curses.color_pair(TASK_COLOR.get(t["status"], 7))
            mark = "▸" if sel else " "
            who = (t["assignee"] or "—")[:10]
            line = f"{mark}{i+1:>3} {STATUS_RU.get(t['status'], t['status'])[:18]:<18} {who:<10} {t['title'][:max(10, half-52)]}"
            stdscr.addnstr(y, 1, line, half - 2, attr)
            y += 1
        if not tasks:
            stdscr.addnstr(1, 2, "задач нет", half - 4, curses.A_DIM)

        # правая колонка: агенты
        self._panel(stdscr, half, 0, w - half, h, "АГЕНТЫ")
        y = 1
        for a in self.state["agents"]:
            if y >= h - 2:
                break
            col = {"running": 2, "ready": 4, "blocked": 1, "idle": 8}[a["status"]]
            attr = curses.color_pair(col)
            name = a["name"][:14]
            stdscr.addnstr(y, half + 1, f"{name:<15}", 16, attr | curses.A_BOLD)
            stdscr.addnstr(y, half + 17, f"{AGENT_STATUS_RU[a['status']]:<16}", 17, attr)
            stdscr.addnstr(y, half + 34,
                           f"в работе {a['running']}  готово {a['ready']}  блок {a['blocked']}  сделано {a['done_n']}",
                           w - half - 36, curses.A_DIM)
            y += 1
            for t in a["tasks"][:2]:
                if y >= h - 2:
                    break
                stdscr.addnstr(y, half + 3, "· " + t["title"][:w - half - 6], w - half - 4, curses.A_DIM)
                y += 1
        if y == 1:
            stdscr.addnstr(1, half + 2, "агентов нет", 20, curses.A_DIM)

    def draw_agents(self, stdscr, h: int, w: int):
        self._panel(stdscr, 0, 0, w, h, "АГЕНТЫ И ИХ ЗАДАЧИ")
        y = 1
        for a in self.state["agents"]:
            if y >= h - 2:
                break
            col = {"running": 2, "ready": 4, "blocked": 1, "idle": 8}[a["status"]]
            stdscr.addnstr(y, 1, a["name"], 16, curses.color_pair(col) | curses.A_BOLD)
            stdscr.addnstr(y, 17, AGENT_STATUS_RU[a["status"]], 18, curses.color_pair(col))
            stdscr.addnstr(y, 36, f"в работе {a['running']} · готово {a['ready']} · блок {a['blocked']} · выполнено {a['done_n']}",
                           w - 38, curses.A_DIM)
            y += 1
            for t in a["tasks"][:6]:
                if y >= h - 2:
                    break
                stdscr.addnstr(y, 4, f"[{STATUS_RU.get(t['status'], t['status'])}] {t['title'][:w-24]}",
                               w - 6, curses.A_DIM)
                y += 1
            for t in a["done"][:3]:
                if y >= h - 2:
                    break
                stdscr.addnstr(y, 4, f"[выполнено] {t['title'][:w-24]}", w - 6, curses.A_DIM)
                y += 1
            y += 1

    def draw_chat(self, stdscr, h: int, w: int):
        self._panel(stdscr, 0, 0, w, h, "ПЕРЕПИСКА")
        y = 1
        feed = [f for f in self.state["feed"] if not self.project or f["task_title"] or True][-40:]
        for m in reversed(feed[-max(1, h - 4):]):
            if y >= h - 2:
                break
            ts = time.strftime("%H:%M", time.localtime(m["ts"])) if m["ts"] else ""
            who = m["author"]
            attr = curses.A_BOLD if who == "оператор" else curses.A_NORMAL
            if who == "оператор":
                attr |= curses.color_pair(6)
            stdscr.addnstr(y, 1, f"{ts} {who}: ", 22, attr)
            body = m["body"].replace("\n", " ")
            stdscr.addnstr(y, 23, body[:w - 25], w - 25, curses.A_DIM)
            y += 1

    def draw_proposals(self, stdscr, h: int, w: int):
        self._panel(stdscr, 0, 0, w, h, "ПРЕДЛОЖЕНИЯ (скиллы и cron) — a=утвердить, r=отклонить")
        y = 1
        pending = [p for p in self.proposals if p.get("status") in (None, "pending", "proposed")]
        for p in self.proposals:
            if y >= h - 2:
                break
            st = p.get("status") or "pending"
            end = "✓лидер" if p.get("endorsed") else ("✗лидер" if p.get("endorsed") is False else "—ждёт")
            col = 6 if st == "pending" else (2 if st == "approved" else 1)
            sel = (y - 1) == self.row
            attr = curses.color_pair(col)
            if sel:
                attr |= curses.A_REVERSE | curses.A_BOLD
            head = f"{st.upper():<9} {p.get('kind', '?'):<6} {end:<8} {p.get('name', 'без имени')}"
            stdscr.addnstr(y, 1, head, w - 2, attr)
            y += 1
            if sel:
                for line in str(p.get("why", "")).splitlines()[:4]:
                    if y >= h - 2:
                        break
                    stdscr.addnstr(y, 4, line[:w - 6], w - 6, curses.A_DIM)
                    y += 1
            y += 1
        if not self.proposals:
            stdscr.addnstr(1, 2, "предложений нет — агенты могут прислать их в канал или в папку vault/Агенты/Предложения",
                           w - 4, curses.A_DIM)
        pending = [p for p in self.proposals if p.get("status") in (None, "pending", "proposed")]
        if pending:
            # счётчик в заголовке, а не в self.msg: сообщение пользователя не должно затираться
            stdscr.addnstr(0, max(2, w - 40), f"необработанных: {len(pending)}", min(38, w - 2), curses.A_BOLD)

    def draw_money(self, stdscr, h: int, w: int):
        self._panel(stdscr, 0, 0, w, h, "ДЕНЬГИ")
        m = self.money
        y = 1
        stdscr.addnstr(y, 1, f"ВСЕГО ПОДТВЕРЖДЕНО: {m.get('total_usd', 0):.2f} USD", w - 2, curses.A_BOLD | curses.color_pair(2))
        y += 2
        for it in m.get("items", []):
            if y >= h - 2:
                break
            stdscr.addnstr(y, 1, f"{it.get('date','?'):<12} {str(it.get('channel',''))[:20]:<20} {it.get('amount',''):>10} {str(it.get('status',''))[:16]:<16} {str(it.get('proof',''))[:40]}",
                           w - 2, curses.A_NORMAL)
            y += 1
        if not m.get("items"):
            stdscr.addnstr(y, 1, "записей нет. Файл: vault/Агенты/Деньги.json", w - 2, curses.A_DIM)

    def _panel(self, stdscr, x, y, w, h, title):
        try:
            stdscr.attron(curses.color_pair(4))
            stdscr.addnstr(y, x + 2, title, max(4, w - 4), curses.A_BOLD)
            stdscr.attroff(curses.color_pair(4))
        except curses.error:
            pass
        for i in range(x, x + w):
            try:
                stdscr.addnstr(y, i, "─", 1)
            except curses.error:
                pass
        for i in range(x, x + w):
            try:
                stdscr.addnstr(y + h - 1, i, "─", 1)
            except curses.error:
                pass
        for j in range(y, y + h):
            try:
                stdscr.addnstr(j, x, "│", 1)
                stdscr.addnstr(j, x + w - 1, "│", 1)
            except curses.error:
                pass

    # ---- главный цикл
    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        stdscr.nodelay(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except Exception:
            pass
        stdscr.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        for i in range(1, 8):
            try:
                curses.init_pair(i, i, -1)
            except Exception:
                pass

        while True:
            self.refresh()
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            # шапка
            stdscr.addnstr(0, 2, f" Hermes · агенты · проект: {self.project or 'все'} ", min(w - 2, 70),
                           curses.A_REVERSE | curses.A_BOLD)
            tabs = "  ".join(f"[{i+1}:{t}]" for i, t in enumerate(self.tabs))
            stdscr.addnstr(0, min(w - len(tabs) - 4, 74), tabs, max(0, w - 78), curses.A_BOLD)
            # тело
            body_h = h - 2
            if self.screen_tab == 0:
                self.draw_board(stdscr, body_h, w)
            elif self.screen_tab == 1:
                self.draw_agents(stdscr, body_h, w)
            elif self.screen_tab == 2:
                self.draw_chat(stdscr, body_h, w)
            elif self.screen_tab == 3:
                self.draw_proposals(stdscr, body_h, w)
            else:
                self.draw_money(stdscr, body_h, w)
            # низ: подсказка и сообщение
            if self.screen_tab == 3:
                keys = "1-5 экран · ↑↓ выбор · a утвердить · r отклонить · s написать лидеру · w разбудить · q выход"
            else:
                keys = "1-5 экран · ↑↓ выбор · a назначить · b блок · u разблок · c закрыть · s написать лидеру · w разбудить · q выход"
            stdscr.addnstr(h - 1, 1, keys[:w - 2], w - 2, curses.A_DIM)
            if self.msg:
                stdscr.addnstr(h - 2, 1, ("! " if self.msg_kind else "") + self.msg[:w - 4], w - 2,
                               curses.A_REVERSE | (curses.color_pair(1) if self.msg_kind else 0))
            if self.input_mode:
                stdscr.addnstr(h - 3, 1, f"{self.input_mode}: {self.input}"[:w - 2], w - 2, curses.A_BOLD)
            stdscr.refresh()
            self.handle_key(stdscr)
            time.sleep(0.15)

    # ---- клавиши
    def handle_key(self, stdscr):
        try:
            ch = stdscr.getch()
        except Exception:
            return
        if ch == -1:
            return
        if self.input_mode:
            self.handle_input(ch)
            return
        if ch in (ord("q"), 27):
            raise SystemExit(0)
        if ord("1") <= ch <= ord("5"):
            self.screen_tab = ch - ord("1")
            self.row = 0
            return
        if ch == curses.KEY_UP:
            self.row = max(0, self.row - 1)
            return
        if ch == curses.KEY_DOWN:
            self.row += 1
            return
        if ch == curses.KEY_MOUSE:
            self.handle_mouse(stdscr)
            return
        if ch == ord("a"):
            if self.screen_tab == 3:
                self.approve_current()
            else:
                self.ask_assign()
        elif ch == ord("r"):
            if self.screen_tab == 3:
                self.reject_current()
            else:
                self.refresh(force=True)
                self.notice("обновлено")
        elif ch == ord("b"):
            self.ask_block()
        elif ch == ord("u"):
            self.act("unblock", "разблокировано")
        elif ch == ord("c"):
            self.act("complete", "задача закрыта")
        elif ch == ord("s"):
            self.input_mode = "Указание команде"
            self.input = ""
        elif ch == ord("w"):
            code, out = wake_leader(self.project or "")
            self.notice("лидер разбужен" if code == 0 else f"ошибка: {out[:80]}", 0 if code == 0 else 1)

    def handle_mouse(self, stdscr):
        try:
            _, mx, my, _, _ = curses.getmouse()
        except Exception:
            return
        h, w = stdscr.getmaxyx()
        if my >= h - 2:
            return
        if self.screen_tab == 0:
            half = w // 2
            if mx < half:
                idx = my - 1
                tasks = self.visible_tasks()
                if 0 <= idx < len(tasks):
                    self.row = idx
                    self.focus_task = tasks[idx]
                    self.notice(f"выбрана задача: {tasks[idx]['title'][:60]}")
            else:
                agents = self.state["agents"]
                idx = my - 1
                if 0 <= idx < len(agents):
                    self.screen_tab = 1
                    self.row = 0
                    self.notice(f"агент: {agents[idx]['name']}")
        elif self.screen_tab == 3:
            idx = my - 1
            props = self.proposals
            if 0 <= idx < len(props):
                self.row = idx
                self.notice(f"предложение: {props[idx].get('name')}")

    def handle_input(self, ch):
        if ch in (10, 13):
            text = self.input.strip()
            mode = self.input_mode
            self.input = ""
            self.input_mode = ""
            if not text:
                return
            if mode.startswith("Указание"):
                code, out = send_to_channel(self.project or "", text)
                self.notice(out[:120] if code == 0 else f"ошибка: {out[:120]}", 0 if code == 0 else 1)
            elif mode.startswith("Назначить"):
                code, out = kanban("assign", getattr(self, "focus_task", {}).get("id", ""), text)
                self.notice(out[:120] if code == 0 else f"ошибка: {out[:120]}", 0 if code == 0 else 1)
            elif mode.startswith("Причина") and self.screen_tab == 3:
                props = self.proposals
                if self.row < len(props):
                    code, out = reject_proposal(props[self.row], text)
                    self.notice(out[:120] if code == 0 else f"ошибка: {out[:120]}", 0 if code == 0 else 1)
            elif mode.startswith("Причина"):
                code, out = kanban("block", getattr(self, "focus_task", {}).get("id", ""), text)
                self.notice(out[:120] if code == 0 else f"ошибка: {out[:120]}", 0 if code == 0 else 1)
            self.refresh(force=True)
        elif ch == 27:
            self.input = ""
            self.input_mode = ""
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.input = self.input[:-1]
        elif 32 <= ch < 127:
            self.input += chr(ch)

    def approve_current(self):
        props = self.proposals
        if not props or self.row >= len(props):
            self.notice("предложение не выбрано", 1)
            return
        prop = props[self.row]
        code, out = approve_proposal(prop)
        self.notice(out[:150] if code == 0 else f"ошибка: {out[:150]}", 0 if code == 0 else 1)
        self.refresh(force=True)

    def reject_current(self):
        props = self.proposals
        if not props or self.row >= len(props):
            self.notice("предложение не выбрано", 1)
            return
        self.input_mode = "Причина отклонения"
        self.input = ""

    def ask_assign(self):
        t = getattr(self, "focus_task", None)
        if not t:
            self.notice("сначала выберите задачу мышью", 1)
            return
        self.input_mode = "Назначить (имя агента)"
        self.input = ""

    def ask_block(self):
        t = getattr(self, "focus_task", None)
        if not t:
            self.notice("сначала выберите задачу мышью", 1)
            return
        self.input_mode = "Причина блокировки"
        self.input = ""

    def act(self, action: str, ok_msg: str):
        t = getattr(self, "focus_task", None)
        if not t:
            self.notice("сначала выберите задачу мышью", 1)
            return
        code, out = kanban(action, t["id"])
        self.notice(ok_msg if code == 0 else f"ошибка: {out[:120]}", 0 if code == 0 else 1)
        self.refresh(force=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    a = ap.parse_args()
    tui = Tui(a.project)
    try:
        tui.run()
    except SystemExit:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
