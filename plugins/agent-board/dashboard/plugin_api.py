"""Agent board — dashboard plugin backend.

Монтируется как /api/plugins/agent-board/ плагином Hermes-дашборда.
Читает канбан-базу и реестр Agora, отдаёт состояние проектов, агентов и ленты.
Принимает сообщение оператора в командный канал и будит лидера.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover — вне дашборда
    APIRouter = None  # type: ignore
    BaseModel = object  # type: ignore

log = logging.getLogger(__name__)

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) if (os := __import__("os")) else Path.home() / ".hermes"
KANBAN_DB = HERMES_HOME / "kanban.db"
PLUGIN_DIR = HERMES_HOME / "plugins" / "agora"

if APIRouter:
    router = APIRouter(tags=["agent-board"])


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{KANBAN_DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _agora_roster(project: str) -> list[dict]:
    """Воркеры команды Agora, включая тех, у кого сейчас нет задач."""
    if not (PLUGIN_DIR / "agora").is_dir():
        return []
    import importlib
    import sys
    import types

    if str(PLUGIN_DIR.parent) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR.parent))
    ns = sys.modules.get("hermes_plugins")
    if ns is None:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    pkg = "hermes_plugins.agora"
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PLUGIN_DIR)]
        mod.__package__ = pkg
        sys.modules[pkg] = mod
    try:
        tm = importlib.import_module("hermes_plugins.agora.agora.team_manager")
        team = tm.get_team_for_project(project) or tm.get_team("site-factory")
        if not team:
            return []
        return [{"name": w["name"], "role": w.get("role", "")} for w in team.get("workers", [])]
    except Exception as exc:  # noqa: BLE001
        log.debug("roster lookup failed: %s", exc)
        return []


def _tasks(project: str | None = None) -> list[dict]:
    con = _db()
    try:
        rows = con.execute(
            "SELECT id, title, status, assignee, tenant, created_at, completed_at "
            "FROM tasks ORDER BY created_at DESC LIMIT 400"
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        proj = (r["tenant"] or "default").replace("agora-", "")
        if project and proj != project:
            continue
        out.append({
            "id": r["id"],
            "title": (r["title"] or "").replace("[Motion] ", "").strip(),
            "status": r["status"] or "todo",
            "assignee": r["assignee"] or "",
            "project": proj,
            "created_at": r["created_at"],
            "completed_at": r["completed_at"],
        })
    return out


def _feed(tasks: list[dict], limit: int = 120) -> list[dict]:
    titles = {t["id"]: t["title"] for t in tasks}
    projects = {t["id"]: t["project"] for t in tasks}
    con = _db()
    try:
        rows = con.execute(
            "SELECT task_id, author, body, created_at FROM task_comments "
            "ORDER BY created_at DESC LIMIT ?", (limit * 3,)
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
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
        out.append({
            "task_id": r["task_id"],
            "task_title": titles.get(r["task_id"], ""),
            "project": projects.get(r["task_id"], ""),
            "author": author,
            "body": body,
            "ts": r["created_at"],
        })
        if len(out) >= limit:
            break
    return out


def _agents_of(tasks: list[dict], project: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(t["assignee"] or "без исполнителя", []).append(t)
    for w in _agora_roster(project):
        groups.setdefault(w["name"], [])
    order = {"running": 0, "blocked": 1, "ready": 2, "todo": 3}
    out = []
    for name, items in groups.items():
        cur = [t for t in items if t["status"] in order]
        done = [t for t in items if t["status"] == "done"]
        cur.sort(key=lambda t: order.get(t["status"], 9))
        done.sort(key=lambda t: t["completed_at"] or 0, reverse=True)
        status = "idle"
        if any(t["status"] == "running" for t in items):
            status = "running"
        elif any(t["status"] == "blocked" for t in items):
            status = "blocked"
        elif any(t["status"] == "ready" for t in items):
            status = "ready"
        out.append({
            "name": name,
            "status": status,
            "counts": {
                "running": sum(1 for t in items if t["status"] == "running"),
                "ready": sum(1 for t in items if t["status"] == "ready"),
                "blocked": sum(1 for t in items if t["status"] == "blocked"),
                "todo": sum(1 for t in items if t["status"] == "todo"),
                "done": len(done),
            },
            "current": cur[:40],
            "done": done[:15],
        })
    out.sort(key=lambda a: (-a["counts"]["running"], a["name"]))
    return out


if APIRouter:

    @router.get("/projects")
    def list_projects():
        tasks = _tasks()
        feed = _feed(tasks, 300)
        by_proj: dict[str, list[dict]] = {}
        for t in tasks:
            by_proj.setdefault(t["project"], []).append(t)
        out = []
        for name, items in sorted(by_proj.items()):
            cnt = {"running": 0, "ready": 0, "todo": 0, "blocked": 0, "done": 0}
            for t in items:
                if t["status"] in cnt:
                    cnt[t["status"]] += 1
            last = next((f for f in feed if f["project"] == name), None)
            out.append({"name": name, **cnt, "total": len(items),
                        "last": (last["body"][:160] if last else ""),
                        "last_author": (last["author"] if last else "")})
        return {"projects": out}

    @router.get("/project/{name}")
    def get_project(name: str):
        tasks = _tasks(name)
        feed = _feed(tasks, 300)
        con = _db()
        try:
            row = con.execute(
                "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
                (f"agora-{name}",),
            ).fetchone()
        finally:
            con.close()
        return {
            "name": name,
            "agents": _agents_of(tasks, name),
            "feed": [f for f in feed if f["project"] == name],
            "channel": row["id"] if row else None,
            "generated": time.time(),
        }

    class SayRequest(BaseModel):
        project: str
        text: str = Field(..., min_length=1, max_length=8000)

    @router.post("/say")
    def post_say(req: "SayRequest"):
        name = req.project.replace("agora-", "")
        con = sqlite3.connect(KANBAN_DB, timeout=15)
        try:
            row = con.execute(
                "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
                (f"agora-{name}",),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=400, detail="командный канал проекта не найден")
            task_id = row[0]
            # Формат [agora:msg] — лидер читает канал только через agora_read_chat,
            # который парсит лишь структурные сообщения.
            payload = json.dumps({"type": "mention", "author": "оператор",
                                  "content": req.text.strip(), "target": "leader"},
                                 ensure_ascii=False)
            con.execute(
                "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
                (task_id, "оператор", "[agora:msg] " + payload, time.time()),
            )
            con.commit()
        finally:
            con.close()
        try:
            import subprocess
            subprocess.Popen(["hermes", "cron", "run", f"heartbeat-{name}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "task_id": task_id}
