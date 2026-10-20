#!/usr/bin/env python3
"""browser_session.py — доступ к браузерным сессиям для агентов.

Один Chrome-профиль = один набор сессий (X, Kwork, Google). Агентам не нужно
получать и хранить токены: они подключаются к тому же браузеру по CDP и
работают в его сессии.

Порты:
  9222  — chrome-debug: Kwork, X, Google, 2ГИС
  9224  — chrome-gmail: Gmail (рассылка), Google

Использование:
    python3 browser_session.py cookies 9222 x.com        # достать cookie по имени
    python3 browser_session.py check  9222 https://x.com/home
    python3 browser_session.py pages  9222
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

import websockets

LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def pages(port: int) -> list[dict]:
    return json.load(LOCAL.open(f"http://127.0.0.1:{port}/json/list", timeout=15))


def new_tab(port: int, url: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
    return json.load(LOCAL.open(req, timeout=20))


async def _cdp(tab: dict, expression: str, wait: float = 6.0) -> object:
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=20_000_000, proxy=None) as ws:
        i = 0

        async def call(m, **p):
            nonlocal i
            i += 1
            await ws.send(json.dumps({"id": i, "method": m, "params": p}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if msg.get("id") == i:
                    return msg.get("result", {})

        await call("Network.enable")
        await call("Page.enable")
        await call("Runtime.evaluate", expression=f"(() => {{ location.href={json.dumps(expression)}; return 1; }})()")
        await asyncio.sleep(wait)
        r = await call("Runtime.evaluate",
                       expression="({url: location.href, title: document.title, text: document.body.innerText.slice(0,400)})",
                       returnByValue=True)
        return r.get("result", {}).get("value", {})


def cmd_pages(port: int) -> int:
    for p in pages(port):
        if p.get("type") == "page":
            print(f"  {(p.get('title') or '')[:50]:<52} {p.get('url','')[:80]}")
    return 0


def cmd_cookies(port: int, domain: str) -> int:
    """Достать cookie по имени для домена через CDP — так сессия видна агенту."""
    tab = next((p for p in pages(port) if p.get("type") == "page"), None)
    if tab is None:
        print("нет вкладок", file=sys.stderr)
        return 1

    async def go():
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=20_000_000, proxy=None) as ws:
            i = 0

            async def call(m, **p):
                nonlocal i
                i += 1
                await ws.send(json.dumps({"id": i, "method": m, "params": p}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == i:
                        return msg.get("result", {})

            await call("Network.enable")
            r = await call("Network.getCookies", urls=[f"https://{domain}/"])
            return r.get("cookies", [])

    cookies = asyncio.run(go())
    out = {c["name"]: c["value"] for c in cookies}
    for k, v in out.items():
        print(f"{k}={v[:60]}{'…' if len(v) > 60 else ''}")
    return 0 if out else 1


def cmd_check(port: int, url: str) -> int:
    tab = next((p for p in pages(port) if p.get("type") == "page"), None)
    if tab is None:
        print("нет вкладок", file=sys.stderr)
        return 1
    res = asyncio.run(_cdp(tab, url))
    print(json.dumps(res, ensure_ascii=False, indent=1)[:1200])
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    port = int(sys.argv[2])
    if cmd == "pages":
        return cmd_pages(port)
    if cmd == "cookies":
        return cmd_cookies(port, sys.argv[3])
    if cmd == "check":
        return cmd_check(port, sys.argv[3])
    print("неизвестная команда", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
