#!/usr/bin/env python3
"""agent_board.py — карта работы агентов, отдельная страница на каждый проект.

    python3 agent_board.py --port 9121

Страницы:
    /                  — список проектов
    /p/<проект>        — один проект: агенты пузырями, статус цветом и анимацией

Пузырь — агент, а не задача. Наведение показывает задачи в работе, клик открывает
панель с текущими и выполненными задачами. Справа — переписка: что написал
оператор и что ответила команда.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB = Path.home() / ".hermes" / "kanban.db"
PLUGIN = Path.home() / ".hermes" / "plugins" / "agora"


def _agora_roster(project: str) -> list[dict]:
    """Воркеры команды Agora, даже если у них сейчас нет задач в канбане.

    Без этого агент, которого только что наняли, не виден на карте — а именно
    это и нужно заметить в первую очередь.
    """
    if not (PLUGIN / "agora").is_dir():
        return []
    import importlib
    import sys
    import types

    if str(PLUGIN.parent) not in sys.path:
        sys.path.insert(0, str(PLUGIN.parent))
    ns = sys.modules.get("hermes_plugins")
    if ns is None:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    pkg = "hermes_plugins.agora"
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PLUGIN)]
        mod.__package__ = pkg
        sys.modules[pkg] = mod
    try:
        tm = importlib.import_module("hermes_plugins.agora.agora.team_manager")
        team = tm.get_team_for_project(project) or tm.get_team("site-factory")
        if not team:
            return []
        return [{"name": w["name"], "role": w.get("role", "")} for w in team.get("workers", [])]
    except Exception:
        return []


# ---------------------------------------------------------------- данные

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _tasks(con: sqlite3.Connection, project: str | None = None) -> list[dict]:
    q = ("SELECT id, title, status, assignee, tenant, created_at, completed_at "
         "FROM tasks ORDER BY created_at DESC LIMIT 400")
    out = []
    for r in con.execute(q):
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


def _feed(con: sqlite3.Connection, tasks: list[dict], limit: int = 120) -> list[dict]:
    titles = {t["id"]: t["title"] for t in tasks}
    projects = {t["id"]: t["project"] for t in tasks}
    out = []
    for r in con.execute(
        "SELECT task_id, author, body, created_at FROM task_comments "
        "ORDER BY created_at DESC LIMIT ?", (limit * 3,)
    ):
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


def projects_state() -> list[dict]:
    con = _conn()
    try:
        tasks = _tasks(con)
        feed = _feed(con, tasks, 300)
    finally:
        con.close()
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
    return out


def project_state(name: str) -> dict:
    con = _conn()
    try:
        tasks = _tasks(con, name)
        feed = _feed(con, tasks, 300)
        row = con.execute(
            "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
            (f"agora-{name}",),
        ).fetchone()
        channel = row["id"] if row else None
    finally:
        con.close()

    agents: dict[str, list[dict]] = {}
    for t in tasks:
        agents.setdefault(t["assignee"] or "без исполнителя", []).append(t)

    for w in _agora_roster(name):
        agents.setdefault(w["name"], [])

    out_agents = []
    order = {"running": 0, "blocked": 1, "ready": 2, "todo": 3}
    for aname, items in agents.items():
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
        out_agents.append({
            "name": aname,
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
    out_agents.sort(key=lambda a: (-a["counts"]["running"], a["name"]))
    return {"name": name, "agents": out_agents,
            "feed": [f for f in feed if f["project"] == name],
            "channel": channel, "generated": time.time()}


def post_message(project: str, text: str) -> dict:
    name = project.replace("agora-", "")
    con = sqlite3.connect(DB, timeout=15)
    try:
        row = con.execute(
            "SELECT id FROM tasks WHERE tenant = ? AND status = 'scheduled' ORDER BY created_at LIMIT 1",
            (f"agora-{name}",),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "командный канал проекта не найден"}
        task_id = row[0]
        # Формат [agora:msg] — иначе лидер, читающий канал через agora_read_chat,
        # сообщение оператора не увидит: он читает только структурные сообщения.
        payload = json.dumps({"type": "mention", "author": "оператор",
                              "content": text, "target": "leader"},
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
    except Exception:
        pass
    return {"ok": True, "task_id": task_id}


# ---------------------------------------------------------------- разметка

COMMON_CSS = """
  :root { --bg:#0b1020; --panel:#121a2b; --line:#22304a; --text:#e7eefb; --muted:#8ba0bf;
          --run:#22c55e; --ready:#3b82f6; --todo:#94a3b8; --blocked:#ef4444; --done:#4b5b70;
          --accent:#3b82f6; }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--bg); color: var(--text); overflow: hidden;
         font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
  a { color: var(--accent); text-decoration: none; }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
"""

INDEX_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Проекты агентов</title><style>%CSS%
  body { overflow:auto; padding:28px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:22px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:16px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px;
          display:block; color:var(--text); transition:border-color .15s; }
  .card:hover { border-color:var(--accent); }
  .card h2 { margin:0 0 8px; font-size:17px; }
  .row { display:flex; gap:12px; color:var(--muted); font-size:12.5px; margin-bottom:10px; flex-wrap:wrap; }
  .row span { display:flex; align-items:center; gap:5px; }
  .last { color:#9db0cd; font-size:12.5px; border-top:1px solid var(--line); padding-top:10px;
          display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
</style></head><body>
<h1>Проекты агентов</h1>
<div class="sub">Каждый проект — отдельная страница. Нажмите карточку.</div>
<div class="grid" id="grid"></div>
<script>
function esc(s){return (s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
async function go(){
  const r = await fetch('/api/projects',{cache:'no-store'});
  const d = await r.json();
  document.getElementById('grid').innerHTML = d.projects.map(p => `
    <a class="card" href="/p/${encodeURIComponent(p.name)}">
      <h2>${esc(p.name)}</h2>
      <div class="row">
        <span><i class="dot" style="background:var(--run)"></i>${p.running} работает</span>
        <span><i class="dot" style="background:var(--ready)"></i>${p.ready} готовы</span>
        <span><i class="dot" style="background:var(--blocked)"></i>${p.blocked} блок</span>
        <span><i class="dot" style="background:var(--done)"></i>${p.done} сделано</span>
      </div>
      <div class="last">${esc(p.last_author)}: ${esc(p.last)}</div>
    </a>`).join('');
}
go(); setInterval(go, 3000);
</script></body></html>"""

PROJECT_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>__NAME__ — карта агентов</title><style>%CSS%
  header { display:flex; align-items:center; gap:14px; height:52px; padding:0 16px; background:var(--panel);
           border-bottom:1px solid var(--line); }
  header h1 { font-size:16px; margin:0; }
  header .back { color:var(--muted); font-size:13px; }
  .stat { display:flex; gap:6px; align-items:center; font-size:13px; color:var(--muted); }
  .spacer { flex:1; }
  #age { color:var(--muted); font-size:12px; }
  #wrap { display:flex; height:calc(100% - 52px); }
  #stage { flex:1; position:relative; min-width:0; }
  canvas { display:block; }
  #side { width:min(460px, 30vw); flex:0 0 min(460px, 30vw); background:var(--panel);
          border-left:1px solid var(--line); display:flex; flex-direction:column; overflow:hidden; }
  #say { padding:10px 12px; border-bottom:1px solid var(--line); display:flex; flex-direction:column; gap:7px; }
  #say textarea { background:#0f1729; color:var(--text); border:1px solid var(--line); border-radius:8px;
                  padding:8px 10px; font:12.5px system-ui; resize:vertical; min-height:46px; }
  #say button { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:9px 12px;
                font:600 13px system-ui; cursor:pointer; }
  #say button:disabled { background:#334155; }
  #say-status { font-size:11.5px; color:var(--muted); }
  .tabs { display:flex; border-bottom:1px solid var(--line); }
  .tabs button { flex:1; background:none; border:0; color:var(--muted); padding:10px 0; font:600 12px system-ui;
                 cursor:pointer; border-bottom:2px solid transparent; }
  .tabs button.active { color:var(--text); border-bottom-color:var(--accent); }
  #body { overflow-y:auto; padding:12px 14px 40px; flex:1 1 auto; min-height:0; }
  .task { border-left:2px solid var(--line); padding:6px 0 6px 10px; margin-bottom:9px; }
  .task .t { font-size:13px; color:#dbe6f7; }
  .task .m { font-size:11.5px; color:var(--muted); margin-top:2px; }
  .task.running { border-left-color:var(--run); }
  .task.ready { border-left-color:var(--ready); }
  .task.blocked { border-left-color:var(--blocked); }
  .task.done { border-left-color:var(--done); opacity:.75; }
  .msg { border-left:2px solid var(--line); padding:6px 0 6px 10px; margin-bottom:10px; }
  .msg.op { border-left-color:var(--accent); background:rgba(59,130,246,.07); }
  .msg b { color:#c7d6ee; font-size:12.5px; }
  .msg .m { color:var(--muted); font-size:11.5px; }
  .msg p { margin:4px 0 0; font-size:13px; color:#c2d0e6; white-space:pre-wrap; }
  .empty { color:var(--muted); font-size:13px; padding:20px 0; text-align:center; }
  #tip { position:absolute; pointer-events:none; background:#0f1729; border:1px solid var(--line);
         border-radius:10px; padding:9px 11px; font-size:12.5px; max-width:400px; display:none; z-index:6; }
  #tip ul { margin:6px 0 0; padding-left:16px; color:#b9c8df; }
  #tip li { margin-bottom:3px; }
  #hint { position:absolute; left:12px; bottom:10px; display:flex; gap:16px; align-items:center;
          color:#c3d3ea; font-size:13px; background:rgba(15,23,41,.95); border:1px solid var(--line);
          border-radius:10px; padding:10px 14px; }
  #hint i { width:11px; height:11px; border-radius:50%; display:inline-block; margin-right:6px; vertical-align:-1px; }
  #hint span { display:flex; align-items:center; white-space:nowrap; }
</style></head><body>
<header>
  <a class="back" href="/">← проекты</a>
  <h1>__NAME__</h1>
  <div class="stat"><i class="dot" style="background:var(--run)"></i><span id="c-run">0 задач в работе</span></div>
  <div class="stat"><i class="dot" style="background:var(--ready)"></i><span id="c-ready">0 готовы к проверке</span></div>
  <div class="stat"><i class="dot" style="background:var(--blocked)"></i><span id="c-blocked">0 заблокировано</span></div>
  <div class="stat"><i class="dot" style="background:var(--done)"></i><span id="c-done">0 выполнено</span></div>
  <div class="spacer"></div><span id="age">обновление…</span>
</header>
<div id="wrap">
  <div id="stage">
    <canvas id="cv"></canvas>
    <div id="tip"></div>
    <div id="hint">
  <span><i style="background:#22c55e"></i>работает</span>
  <span><i style="background:#3b82f6"></i>ждёт запуска</span>
  <span><i style="background:#ef4444"></i>заблокирован</span>
  <span><i style="background:#64748b"></i>свободен</span>
  <span style="color:#8ba0bf">наведение — задачи в работе, клик — все задачи агента</span>
</div>
  </div>
  <div id="side">
    <div id="say">
      <textarea id="say-text" placeholder="Написать команде…"></textarea>
      <button id="say-btn" disabled>Отправить и разбудить лидера</button>
      <span id="say-status"></span>
    </div>
    <div class="tabs">
      <button data-tab="agent" class="active">Агент</button>
      <button data-tab="chat">Переписка</button>
      <button data-tab="all">Все задачи</button>
    </div>
    <div id="body"></div>
  </div>
</div>
<script>
const PROJECT = "__NAME__";
const cv = document.getElementById('cv'), ctx = cv.getContext('2d'), tip = document.getElementById('tip');
const STATUS_COLOR = {running:'#22c55e', ready:'#3b82f6', blocked:'#ef4444', idle:'#64748b'};
let data = {agents: [], feed: []}, bubbles = [], hovered = null, selected = null, tab = 'agent';

function esc(s){return (s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));}
function fmt(ts){ return ts ? new Date(ts*1000).toLocaleString('ru-RU',{hour:'2-digit',minute:'2-digit'}) : ''; }
function statusRu(s){ return {running:'работает', ready:'ждёт запуска', blocked:'заблокирован', idle:'свободен'}[s] || s; }

function resize(){
  const box = cv.parentElement.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = box.width*dpr; cv.height = box.height*dpr;
  cv.style.width = box.width+'px'; cv.style.height = box.height+'px';
  ctx.setTransform(dpr,0,0,dpr,0,0);
  place();
}
window.addEventListener('resize', resize);

function place(){
  const W = cv.clientWidth, H = cv.clientHeight;
  const n = Math.max(data.agents.length, 1);
  // Пузыри по эллипсу почти на всю площадь холста: центр пустым не оставляем.
  const rx = Math.max(120, (W / 2) - 230), ry = Math.max(110, (H / 2) - 170);
  const r = n > 6 ? 46 : n > 4 ? 52 : 58;
  // Лидер — в центре, остальные по кругу: так видно, кто кем управляет.
  const leader = data.agents.find(a => a.name === 'leader');
  const rest = data.agents.filter(a => a.name !== 'leader');
  const m = Math.max(rest.length, 1);
  const placed = [];
  rest.forEach((a, i) => {
    const ang = (i / m) * Math.PI * 2 - Math.PI / 2;
    placed.push(Object.assign({}, a, {
      x: W / 2 + Math.cos(ang) * rx,
      y: H / 2 + Math.sin(ang) * ry,
      r: r
    }));
  });
  bubbles = leader
    ? [Object.assign({}, leader, {x: W / 2, y: H / 2, r: r + 6})].concat(placed)
    : placed;
}

function draw(t){
  const W = cv.clientWidth, H = cv.clientHeight, time = t/1000;
  ctx.clearRect(0,0,W,H);
  // Связи: лидер в центре, от него лучи к остальным — видно, кто кем управляет.
  const hub = bubbles.find(b => b.name === 'leader');
  if (hub) {
    bubbles.filter(b => b !== hub).forEach(b => {
      const dx = b.x - hub.x, dy = b.y - hub.y, d = Math.hypot(dx, dy) || 1;
      const sx = hub.x + dx / d * (hub.r + 10), sy = hub.y + dy / d * (hub.r + 10);
      const ex = b.x - dx / d * (b.r + 8), ey = b.y - dy / d * (b.r + 8);
      ctx.strokeStyle = 'rgba(140,170,220,.42)'; ctx.lineWidth = 1.8;
      ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
    });
  }
  bubbles.forEach(b => {
    const col = STATUS_COLOR[b.status] || '#64748b';
    ctx.beginPath(); ctx.arc(b.x,b.y,b.r+11,0,7); ctx.fillStyle = col + '12'; ctx.fill();

    const g = ctx.createRadialGradient(b.x-14,b.y-16,6,b.x,b.y,b.r);
    g.addColorStop(0,'#25364b'); g.addColorStop(1,'#121b2b');
    ctx.beginPath(); ctx.arc(b.x,b.y,b.r,0,7); ctx.fillStyle = g; ctx.fill();
    ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.stroke();

    if (b.status === 'running') {
      const dots = Math.max(1, Math.min(b.counts.running, 6));
      for (let k=0;k<dots;k++){
        const a = time*2.2 + k*2*Math.PI/dots;
        ctx.beginPath(); ctx.arc(b.x+Math.cos(a)*(b.r+13), b.y+Math.sin(a)*(b.r+13), 3.2, 0, 7);
        ctx.fillStyle = '#22c55e'; ctx.fill();
      }
      ctx.beginPath(); ctx.arc(b.x,b.y,b.r+8+Math.sin(time*3)*2,0,7);
      ctx.strokeStyle='rgba(34,197,94,.30)'; ctx.lineWidth=1.5; ctx.stroke();
    } else if (b.status === 'ready') {
      ctx.save(); ctx.setLineDash([5,7]); ctx.lineDashOffset = -time*14;
      ctx.beginPath(); ctx.arc(b.x,b.y,b.r+10,0,7); ctx.strokeStyle='#3b82f6'; ctx.lineWidth=1.6; ctx.stroke(); ctx.restore();
    } else if (b.status === 'blocked') {
      const p = 0.5+0.5*Math.sin(time*4);
      ctx.beginPath(); ctx.arc(b.x,b.y,b.r+9+p*3,0,7); ctx.strokeStyle='rgba(239,68,68,'+(0.35+0.4*p)+')'; ctx.lineWidth=2; ctx.stroke();
    } else {
      ctx.beginPath(); ctx.arc(b.x,b.y,b.r+8,0,7); ctx.strokeStyle='rgba(100,116,139,.22)'; ctx.lineWidth=1; ctx.stroke();
    }
    if (hovered === b.name || selected === b.name) {
      ctx.beginPath(); ctx.arc(b.x,b.y,b.r+5,0,7); ctx.strokeStyle='#e7eefb'; ctx.lineWidth=1.6; ctx.stroke();
    }
    ctx.textAlign='center';
    ctx.font='600 '+(b.r>50?15:13)+'px system-ui'; ctx.fillStyle='#eef4ff';
    const nm = b.name.length > (b.r>50?12:10) ? b.name.slice(0, b.r>50?12:10) : b.name;
    ctx.fillText(nm, b.x, b.y+1);
    ctx.font='600 '+(b.r>50?13:11.5)+'px system-ui'; ctx.fillStyle = col;
    ctx.fillText(b.counts.running ? b.counts.running+' в работе'
               : (b.counts.ready ? 'ждёт запуска' : 'свободен'), b.x, b.y+21);
    if (b.counts.ready && b.counts.running) {
      ctx.font='12px system-ui'; ctx.fillStyle='#7d97bd';
      ctx.fillText(b.counts.ready+' готовы', b.x, b.y+37);
    }
  });
  requestAnimationFrame(draw);
}

function hit(e){
  const r = cv.getBoundingClientRect(), x = e.clientX-r.left, y = e.clientY-r.top;
  return bubbles.find(b => Math.hypot(b.x-x, b.y-y) <= b.r+8) || null;
}
cv.addEventListener('mousemove', e => {
  const b = hit(e); hovered = b ? b.name : null; cv.style.cursor = b ? 'pointer' : 'default';
  if (!b) { tip.style.display='none'; return; }
  const r = cv.getBoundingClientRect();
  tip.style.display='block';
  tip.style.left = Math.min(e.clientX-r.left+16, cv.clientWidth-420)+'px';
  tip.style.top = Math.max(8, e.clientY-r.top-12)+'px';
  const cur = b.current.slice(0,4);
  tip.innerHTML = '<b>'+esc(b.name)+'</b> — '+esc(statusRu(b.status))+'<ul>'
    + (cur.length ? cur.map(t => '<li>'+esc(t.title)+'</li>').join('') : '<li>задач в работе нет</li>')
    + '</ul>' + (b.current.length > 4 ? '<div style="color:#8ba0bf;margin-top:4px">ещё '+(b.current.length-4)+'</div>' : '');
});
cv.addEventListener('click', e => {
  const b = hit(e);
  if (!b) return;
  selected = b.name; tab = 'agent'; setTab(); render();
});

function setTab(){
  document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('active', x.dataset.tab === tab));
}
document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => {
  tab = btn.dataset.tab; setTab(); render();
}));

function taskHtml(t){
  const when = t.status === 'done' ? fmt(t.completed_at) : '';
  return '<div class="task '+t.status+'"><div class="t">'+esc(t.title)+'</div>'
       + '<div class="m">'+esc(t.status)+(when ? ' · '+when : '')+'</div></div>';
}

function render(){
  const box = document.getElementById('body');
  const agent = bubbles.find(b => b.name === selected);
  if (tab === 'agent') {
    if (!agent) {
      box.innerHTML = '<h3 style="font-size:13px;color:#8ba0bf;margin:2px 0 10px">Агенты проекта</h3>'
        + data.agents.slice().sort((x, y) => (x.name === 'leader' ? -1 : 0) - (y.name === 'leader' ? -1 : 0)).map(a => {
            const first = a.current[0];
            return '<div class="task ' + a.status + '" data-agent="' + esc(a.name) + '">'
              + '<div class="t">' + esc(a.name) + ' · ' + esc(statusRu(a.status)) + '</div>'
              + '<div class="m">в работе ' + a.counts.running + ' · готовы ' + a.counts.ready
              + ' · выполнено ' + a.counts.done + '</div>'
              + (first ? '<div class="m" style="color:#8fa6c8;margin-top:4px">→ '
                  + esc(first.title.length > 70 ? first.title.slice(0, 70) + '…' : first.title) + '</div>' : '')
              + '</div>';
          }).join('')
        + '<div class="empty">Нажмите на пузырь, чтобы открыть задачи агента</div>';
      return;
    }
    box.innerHTML = '<h3 style="font-size:14px;margin:2px 0 4px">'+esc(agent.name)+'</h3>'
      + '<div style="font-size:12px;color:#8ba0bf;margin-bottom:12px">'+esc(statusRu(agent.status))
      + ' · готовы к проверке '+agent.counts.ready+' · выполнено '+agent.counts.done+'</div>'
      + (agent.current.map(taskHtml).join('') || '<div class="empty">Сейчас задач нет</div>')
      + '<h3 style="font-size:13px;color:#8ba0bf;margin:16px 0 8px">Выполнено '+agent.counts.done+'</h3>'
      + (agent.done.map(taskHtml).join('') || '<div class="empty">Пока ничего не выполнено</div>');
  } else if (tab === 'chat') {
    box.innerHTML = data.feed.length ? data.feed.slice(0,80).map(m => {
      const op = m.author === 'оператор' ? ' op' : '';
      return '<div class="msg'+op+'"><b>'+esc(m.author||'—')+'</b><span class="m"> '+fmt(m.ts)+'</span>'
           + '<p>'+esc(m.body)+'</p></div>';
    }).join('') : '<div class="empty">Сообщений пока нет</div>';
  } else {
    const all = [];
    data.agents.forEach(a => a.current.concat(a.done).forEach(t => all.push(Object.assign({who:a.name}, t))));
    const ord = {running:0, blocked:1, ready:2, todo:3};
    all.sort((x,y) => (ord[x.status]||9) - (ord[y.status]||9));
    box.innerHTML = all.length ? all.map(t => '<div class="task '+t.status+'"><div class="t">'+esc(t.title)
      + '</div><div class="m">'+esc(t.who)+' · '+esc(t.status)+'</div></div>').join('')
      : '<div class="empty">Задач нет</div>';
  }
}

const sayText = document.getElementById('say-text'), sayBtn = document.getElementById('say-btn');
sayText.addEventListener('input', () => { sayBtn.disabled = !sayText.value.trim(); });

document.getElementById('say-btn').addEventListener('click', async () => {
  const btn = document.getElementById('say-btn'), st = document.getElementById('say-status');
  const text = document.getElementById('say-text').value.trim();
  if (!text) { st.textContent = 'Пустое сообщение'; return; }
  btn.disabled = true; st.textContent = 'Отправляю…';
  try {
    const r = await fetch('/api/say', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body: JSON.stringify({project: PROJECT, text})});
    const j = await r.json();
    if (j.ok) {
      st.textContent = 'Доставлено, лидер разбужен. Смотрите вкладку «Переписка».';
      document.getElementById('say-text').value = '';
      tab = 'chat'; setTab();
    } else st.textContent = 'Ошибка: ' + (j.error || 'неизвестно');
  } catch(e) { st.textContent = 'Ошибка сети'; }
  btn.disabled = !document.getElementById('say-text').value.trim(); refresh();
});

async function refresh(){
  try {
    const r = await fetch('/api/project/'+encodeURIComponent(PROJECT), {cache:'no-store'});
    data = await r.json();
    place();
    const c = {running:0, ready:0, blocked:0, done:0};
    data.agents.forEach(a => { c.running += a.counts.running; c.ready += a.counts.ready;
                               c.blocked += a.counts.blocked; c.done += a.counts.done; });
    document.getElementById('c-run').textContent = c.running+' задач в работе';
    document.getElementById('c-ready').textContent = c.ready+' готовы к проверке';
    document.getElementById('c-blocked').textContent = c.blocked+' заблокировано';
    document.getElementById('c-done').textContent = c.done+' выполнено';
    document.getElementById('age').textContent = 'обновлено '+new Date().toLocaleTimeString('ru-RU');
    render();
  } catch(e) { document.getElementById('age').textContent='нет связи'; }
}

resize(); refresh(); requestAnimationFrame(draw); setInterval(refresh, 2500);
</script></body></html>"""


MINIAPP_PATH = Path("/home/asd/.hermes/scripts/miniapp.html")
MINIAPP = MINIAPP_PATH.read_text(encoding="utf-8") if MINIAPP_PATH.exists() else ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = (urlparse(self.path).path.rstrip("/") or "/")
        if path == "/":
            self._send(INDEX_PAGE.replace("%CSS%", COMMON_CSS).encode(), "text/html; charset=utf-8")
        elif path == "/miniapp":
            self._send(MINIAPP.encode(), "text/html; charset=utf-8")
        elif path.startswith("/p/"):
            name = path[3:]
            page = PROJECT_PAGE.replace("%CSS%", COMMON_CSS).replace("__NAME__", name)
            self._send(page.encode(), "text/html; charset=utf-8")
        elif path == "/api/projects":
            self._send(json.dumps({"projects": projects_state()}, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8")
        elif path.startswith("/api/project/"):
            name = path[len("/api/project/"):]
            try:
                self._send(json.dumps(project_state(name), ensure_ascii=False).encode(),
                           "application/json; charset=utf-8")
            except Exception as exc:  # noqa: BLE001
                self._send(json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                           "application/json; charset=utf-8", 500)
        else:
            self._send(b"not found", "text/plain", 404)

    def do_OPTIONS(self):
        self._send(b"", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/say":
            self._send(b"not found", "text/plain", 404); return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}")
            res = post_message(str(d.get("project") or ""), str(d.get("text") or "").strip())
            code = 200 if res.get("ok") else 400
        except Exception as exc:  # noqa: BLE001
            res, code = {"ok": False, "error": str(exc)}, 500
        self._send(json.dumps(res, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9121)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"карта: http://{a.host}:{a.port}/", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
