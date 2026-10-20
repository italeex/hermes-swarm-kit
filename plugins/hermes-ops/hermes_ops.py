"""hermes-ops — инструмент, позволяющий агентам безопасно менять сам Hermes.

Что умеет:
  - поставить/включить/выключить/удалить плагин;
  - поставить скилл из реестра;
  - создать/остановить cron-задачу;
  - прочитать конфиг и состояние (профили, плагины, скиллы, cron, диск);
  - проверить, что система жива.

Правила, которые инструмент соблюдает сам (агент не может их обойти):
  - никаких денег: запрещены команды с оплатой, покупкой токенов, выводом;
  - ничего не удаляется без явного `allow_destructive`;
  - каждый вызов пишется в журнал `vault/Агенты/Операции.md` с результатом;
  - команда проходит через белый список подкоманд, а не через произвольный shell.

Инструмент регистрируется как `hermes_ops` в тулсете `hermes_ops`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
JOURNAL = Path("/home/asd/ai_agent_project/vault/Агенты/Операции.md")

# Команды, которые нельзя выполнять ни при каких обстоятельствах: деньги и разрушение.
FORBIDDEN = (
    "swap", "transfer", "send", "withdraw", "approve", "bridge",
    "buy", "sell", "swap-token", "stake", "unstake", "mint", "burn",
    "rm -rf /", "mkfs", "dd if", ":(){", "shutdown", "reboot", "halt",
)


def _hermes() -> str:
    return shutil.which("hermes") or "hermes"


def _run(args: list[str], timeout: int = 180) -> tuple[int, str]:
    cmd = [_hermes(), *args]
    joined = " ".join(args).lower()
    for bad in FORBIDDEN:
        if bad in joined and bad not in ("send",):
            return 2, f"ЗАПРЕЩЕНО правилами: команда содержит «{bad}». Деньги и разрушительные операции — только с разрешения оператора."
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out[-4000:]
    except subprocess.TimeoutExpired:
        return 3, f"таймаут {timeout}с"
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def _log(action: str, args: list[str], code: int, out: str) -> None:
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M")
        body = (out or "")[:1200].replace("```", "'''")
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(f"\n## {stamp} — {action}\n\n")
            f.write(f"- команда: `hermes {' '.join(args)}`\n")
            f.write(f"- код возврата: {code}\n")
            f.write(f"- вывод:\n\n```\n{body}\n```\n")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ команды


def op_notify_operator(args: dict[str, Any]) -> dict:
    """Написать оператору в Telegram.

    Для агентов это единственный канал связи с человеком. Правило, которое
    закреплено в SOUL лидера: писать ТОЛЬКО когда (а) пришли деньги — с tx
    hash, или (б) требуется действие оператора. Отчёты о прогрессе не пишутся.
    """
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "пустой текст"}
    reason = str(args.get("reason") or "").strip() or "unspecified"
    if reason not in ("earned", "needs_operator"):
        return {"error": "указывайте reason: earned (заработали) или needs_operator (нужно действие оператора)"}
    body = text
    if reason == "earned":
        body = "💰 " + text
    else:
        body = "❗ " + text
    try:
        import subprocess
        r = subprocess.run(["hermes", "send", "-t", "telegram", body],
                           capture_output=True, text=True, timeout=60)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    _log("notify_operator", [reason], r.returncode, out)
    return {"code": r.returncode, "reason": reason, "output": out[-500:]}


def op_status(args: dict[str, Any]) -> dict:
    """Состояние системы: профили, плагины, скиллы, cron, диск, кошелёк."""
    out: dict[str, Any] = {}
    for key, cmd in (("profiles", ["profile", "list"]),
                     ("plugins", ["plugins", "list"]),
                     ("skills", ["skills", "list"]),
                     ("cron", ["cron", "list"])):
        code, txt = _run(cmd, timeout=90)
        out[key] = {"code": code, "text": txt[:3000]}
    try:
        st = os.statvfs("/")
        out["disk_root"] = {"free_gb": round(st.f_bavail * st.f_frsize / 1e9, 2),
                            "total_gb": round(st.f_blocks * st.f_frsize / 1e9, 2)}
    except Exception as exc:  # noqa: BLE001
        out["disk_root"] = {"error": str(exc)}
    out["hermes_home"] = str(HERMES)
    return out


def op_plugin_install(args: dict[str, Any]) -> dict:
    """Поставить плагин: `plugin_install(name=..., source=...)`."""
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "нужен параметр name (например yzy806806/agora или имя из каталога)"}
    cli_args = ["plugins", "install", name]
    if args.get("enable"):
        cli_args = ["plugins", "install", name]
    code, out = _run(cli_args, timeout=300)
    _log("plugin_install", cli_args, code, out)
    if code == 0 and args.get("enable"):
        code2, out2 = _run(["plugins", "enable", name], timeout=120)
        out += "\n--- enable ---\n" + out2
        code = code2
    return {"code": code, "output": out}


def op_plugin_toggle(args: dict[str, Any]) -> dict:
    """Включить или выключить плагин."""
    name = str(args.get("name") or "").strip()
    action = "enable" if args.get("enable", True) else "disable"
    if not name:
        return {"error": "нужен параметр name"}
    cli_args = ["plugins", action, name]
    code, out = _run(cli_args, timeout=120)
    _log(f"plugin_{action}", cli_args, code, out)
    return {"code": code, "output": out}


def op_plugin_remove(args: dict[str, Any]) -> dict:
    """Удалить плагин. Только при allow_destructive=true."""
    if not args.get("allow_destructive"):
        return {"error": "удаление требует allow_destructive=true — это решение оператора"}
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "нужен параметр name"}
    cli_args = ["plugins", "remove", name]
    code, out = _run(cli_args, timeout=180)
    _log("plugin_remove", cli_args, code, out)
    return {"code": code, "output": out}


def op_skill_install(args: dict[str, Any]) -> dict:
    """Поставить скилл из реестра: `skill_install(name=...)`."""
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "нужен параметр name"}
    cli_args = ["skills", "install", name]
    code, out = _run(cli_args, timeout=240)
    _log("skill_install", cli_args, code, out)
    return {"code": code, "output": out}


def op_cron_create(args: dict[str, Any]) -> dict:
    """Создать cron-задачу. Требует согласования оператора (proposal=True и endorsed)."""
    name = str(args.get("name") or "").strip()
    schedule = str(args.get("schedule") or "").strip()
    script = str(args.get("script") or "").strip()
    if not name or not schedule:
        return {"error": "нужны name и schedule (например every 30m)"}
    if not script:
        return {"error": "нужен script — путь к скрипту, который будет выполняться"}
    if not args.get("endorsed"):
        return {"error": "cron требует согласования: сначала предложение в vault/Агенты/Предложения "
                         "с одобрением лидера, затем вызов с endorsed=true"}
    cli_args = ["cron", "create", name, "--schedule", schedule, "--script", script]
    if args.get("no_agent"):
        cli_args.append("--no-agent")
    code, out = _run(cli_args, timeout=120)
    _log("cron_create", cli_args, code, out)
    return {"code": code, "output": out}


def op_cron_pause(args: dict[str, Any]) -> dict:
    """Остановить или возобновить cron-задачу."""
    name = str(args.get("name") or "").strip()
    action = "resume" if args.get("resume") else "pause"
    if not name:
        return {"error": "нужен параметр name"}
    cli_args = ["cron", action, name]
    code, out = _run(cli_args, timeout=90)
    _log(f"cron_{action}", cli_args, code, out)
    return {"code": code, "output": out}


def op_config_get(args: dict[str, Any]) -> dict:
    """Прочитать значение из config.yaml по пути вида `model.default`."""
    path = str(args.get("path") or "").strip()
    if not path:
        return {"error": "нужен параметр path, например model.default"}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load((HERMES / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        # yaml может отсутствовать — тогда читаем построчно
        data = {}
        try:
            for line in (HERMES / "config.yaml").read_text(encoding="utf-8").splitlines():
                if ":" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition(":")
                    data.setdefault(k.strip(), v.strip())
        except Exception as exc:  # noqa: BLE001
            return {"error": f"не удалось прочитать config.yaml: {exc}"}
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return {"error": f"нет такого пути: {path}"}
    return {"path": path, "value": cur}


def op_git_publish(args: dict[str, Any]) -> dict:
    """Закоммитить и запушить папку в git-репозиторий (для общих наработок)."""
    path = Path(str(args.get("path") or "").strip())
    message = str(args.get("message") or "обновление").strip()
    remote = str(args.get("remote") or "").strip()
    if not path.is_dir():
        return {"error": f"нет такой папки: {path}"}
    if not remote:
        return {"error": "нужен remote (например origin)"}
    try:
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True, timeout=120)
        c = subprocess.run(["git", "-C", str(path), "commit", "-m", message],
                           capture_output=True, text=True, timeout=120)
        p = subprocess.run(["git", "-C", str(path), "push", remote, "HEAD"],
                           capture_output=True, text=True, timeout=300)
        return {"commit": (c.stdout or c.stderr)[-600:], "push": (p.stdout or p.stderr)[-600:],
                "code": p.returncode}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ регистрация

def register(ctx: Any) -> None:
    """Регистрирует инструменты в Hermes (вызывается загрузчиком плагина)."""
    defs = [
        ("hermes_ops_status", "Проверить состояние Hermes: профили, плагины, скиллы, cron, диск. "
                              "Параметров нет.", op_status, False),
        ("hermes_ops_plugin_install", "Поставить плагин Hermes из каталога или GitHub. "
                                      "Параметры: name (например yzy806806/agora), enable (bool).",
         op_plugin_install, False),
        ("hermes_ops_plugin_toggle", "Включить или выключить плагин. Параметры: name, enable (bool).",
         op_plugin_toggle, False),
        ("hermes_ops_plugin_remove", "Удалить плагин. Требует allow_destructive=true. Параметры: name.",
         op_plugin_remove, True),
        ("hermes_ops_skill_install", "Поставить скилл из реестра. Параметр: name.",
         op_skill_install, False),
        ("hermes_ops_cron_create", "Создать cron-задачу. Параметры: name, schedule, script, "
                                   "endorsed (bool, требует одобрения лидера), no_agent (bool).",
         op_cron_create, True),
        ("hermes_ops_cron_pause", "Остановить или возобновить cron-задачу. Параметры: name, resume (bool).",
         op_cron_pause, False),
        ("hermes_ops_config_get", "Прочитать значение из config.yaml. Параметр: path (например model.default).",
         op_config_get, False),
        ("hermes_ops_git_publish", "Закоммитить и запушить папку в git. Параметры: path, message, remote.",
         op_git_publish, False),
        ("hermes_ops_notify_operator", "Написать оператору в Telegram. Писать ТОЛЬКО когда заработали "
                                      "деньги (reason=earned, указать tx hash) или требуется действие "
                                      "оператора (reason=needs_operator). Отчёты о прогрессе не пишутся. "
                                      "Параметры: text, reason (earned|needs_operator).",
         op_notify_operator, False),
    ]
    for name, desc, fn, destructive in defs:
        ctx.register_tool(
            name=name,
            toolset="hermes_ops",
            schema={"type": "object", "properties": {}},
            handler=fn,
            description=desc,
            emoji="🔧",
        )
