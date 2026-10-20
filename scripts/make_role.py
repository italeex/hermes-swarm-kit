#!/usr/bin/env python3
"""make_role.py — библиотека готовых ролей для команды Agora.

Роль = профиль Hermes + SOUL.md + стартовые скиллы. Файл-шаблон лежит в
`roles/<роль>.md`, отсюда ставится настоящий профиль:

    python3 make_role.py list
    python3 make_role.py show leads
    python3 make_role.py install leads --team site-factory --project demo-sites
    python3 make_role.py install copy --team crypto-squad

Установка не трогает деньги и не создаёт cron'ов: это только профиль и его скиллы.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROLES_DIR = pathlib.Path(__file__).parent / "roles"
PLUGIN_DIR = pathlib.Path.home() / ".hermes" / "plugins" / "agora"
sys.path.insert(0, str(PLUGIN_DIR.parent))

ROLES = {
    "leads": {
        "title": "Охотник за лидами",
        "role": "researcher",
        "goal": "Найти малые компании, у которых нет своего сайта, и принести готовый проверенный список.",
        "skills": ["business-site-presence-check", "site-own-seo-first-visitor-is-weeks"],
        "rules": [
            "Сайтом компании не считаются: карточки 2ГИС, Яндекс.Карт, Zoon, ПроДокторов, "
            "avito, VK, а также авто-страницы вида company.2gis.biz и поддомены справочников "
            "(*.gidm.ru, *.gdekrasa.ru и подобные).",
            "Поле website_tag в базе лидов ПУСТОЕ во всех строках — это не признак «сайта нет», "
            "это незаполненное поле. Признак отсутствия сайта устанавливается только проверкой.",
            "Каждый лид проверяется живым запросом, и в отчёт идёт только то, что проверено.",
            "Адрес берётся из карточки, а не пишется «уточняется».",
        ],
    },
    "copy": {
        "title": "Письма, которые читают",
        "role": "writer",
        "goal": "Писать письма и тексты на страницах так, чтобы это выглядело написанным человеком.",
        "skills": ["sepia", "humanizer"],
        "rules": [
            "Ни одного выдуманного числа, факта, отзыва или цены.",
            "Конкретный измеренный дефект вместо «ваш сайт устарел».",
            "Не длиннее 7 строк, последняя строка — один понятный следующий шаг.",
            "Опт-аут «Если не интересно, просто скажите, и я больше не напишу».",
            "Подпись — как у человека, который пишет от своего имени.",
        ],
    },
    "designer": {
        "title": "Вёрстка под клиента",
        "role": "developer",
        "goal": "Собирать одностраничники, которые выглядят лучше текущего сайта клиента и правятся глазами.",
        "skills": ["popular-web-designs", "claude-design", "demo-page-visual-gate"],
        "rules": [
            "Один файл index.html, без внешних зависимостей и запросов.",
            "Цены-примеры помечены как пример, бейдж «демо» заметен.",
            "Перед показом клиенту — скриншот 390 px и проверка глазами, потом правка и новый скриншот.",
            "Никаких выдуманных фактов о компании.",
        ],
    },
    "watcher": {
        "title": "Сторож",
        "role": "devops",
        "goal": "Следить за каналами, диском, почтой и живыми заявками и докладывать только об изменениях.",
        "skills": ["watcher-output-file-hygiene", "host-load-attribution-before-self-limiting"],
        "rules": [
            "Сторож пишет в свой файл, а не в общий лог, и молчит, если ничего не изменилось.",
            "Каждый сторож сам себя останавливает, когда цель достигнута или канал мёртв.",
            "Новый cron — только через предложение в vault/Агенты/Предложения.",
        ],
    },
    "sourcer": {
        "title": "Источник дохода",
        "role": "sourcer",
        "goal": "Найти, где реально платят, доказать живым запросом и передать заявку команде.",
        "skills": ["bounty-payout-rail-truth-table", "agent-task-claim-to-payout"],
        "rules": [
            "Платёжный рельс проверяется живым запросом ДО начала работы.",
            "Мёртвый канал закрывается с доказательством, почему он мёртв.",
            "Ни одной цифры, которая не измерена в этой сессии.",
        ],
    },
}


def build_soul(name: str, spec: dict) -> str:
    lines = [
        f"# {name} — {spec['title']}",
        "",
        f"Ты — **{name}**, {spec['goal']}",
        "",
        "## Что ты делаешь",
        "",
    ]
    for i, rule in enumerate(spec["rules"], 1):
        lines.append(f"{i}. {rule}")
    lines += [
        "",
        "## Инструменты",
        "",
        "У тебя есть: `terminal`, `file`, `web`, `skills`, `todo`, `session_search`.",
        "Рабочая папка проекта и его AGENTS.md — источник правды о текущей цели.",
        "",
        "## Отчётность",
        "",
        "Русский, коротко, по фактам. После каждого значимого шага — запись в журнал проекта:",
        "`/home/asd/ai_agent_project/vault/Агенты/Журнал - <проект>.md`,",
        "формат `## ГГГГ-ММ-ДД ЧЧ:ММ — что сделано`, ниже 2–5 строк: результат, чем подтверждено, что дальше.",
        "",
        "## Жёсткие ограничения",
        "",
        "- Один кошелёк: `0xC9D0aB76b5e9CBE3Da320347cCDAa111e515e6D0`, сеть Base.",
        "- Газ не больше 0.0002 ETH за транзакцию и 0.0005 ETH в сутки.",
        "- Без разрешения оператора: покупки, подписки, пополнения, залоги, переводы, новые кошельки.",
        "- Скилл, cron или скрипт самому не создавать — только предложение в",
        "  `vault/Агенты/Предложения/`, с объяснением, зачем он и почему сейчас.",
        "",
    ]
    return "\n".join(lines)


def cmd_list() -> int:
    print("ГОТОВЫЕ РОЛИ:\n")
    for name, spec in ROLES.items():
        print(f"  {name:<10} {spec['title']:<28} роль: {spec['role']:<10} скиллы: {', '.join(spec['skills'])}")
    print("\nпоставить:  python3 make_role.py install <роль> --team <команда> [--project <проект>]")
    return 0


def cmd_show(name: str) -> int:
    spec = ROLES.get(name)
    if not spec:
        print(f"нет роли '{name}'. Доступные: {', '.join(ROLES)}")
        return 1
    print(build_soul(name, spec))
    return 0


def cmd_install(name: str, team: str, project: str | None) -> int:
    spec = ROLES.get(name)
    if not spec:
        print(f"нет роли '{name}'. Доступные: {', '.join(ROLES)}")
        return 1
    import importlib
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
    wm = importlib.import_module("hermes_plugins.agora.agora.worker_manager")
    tm = importlib.import_module("hermes_plugins.agora.agora.team_manager")

    res = wm.create_worker(name=name, role=spec["role"])
    if isinstance(res, dict) and res.get("error"):
        if "already exists" in str(res.get("error")):
            print(f"профиль {name} уже есть, обновляю SOUL")
        else:
            print("ошибка:", res["error"][:300])
            return 1
    else:
        print(f"профиль {name} создан")

    soul = pathlib.Path.home() / ".hermes" / "profiles" / name / "SOUL.md"
    soul.write_text(build_soul(name, spec), encoding="utf-8")
    print(f"SOUL.md записан: {soul}")

    prof_skills = pathlib.Path.home() / ".hermes" / "profiles" / name / "skills"
    prof_skills.mkdir(parents=True, exist_ok=True)
    for s in spec["skills"]:
        target = prof_skills / s
        target.mkdir(exist_ok=True)
        (target / "SKILL.md").write_text(
            f"---\nname: {s}\ndescription: Скилл роли «{name}» ({spec['title']}). "
            f"Содержимое берётся из общей библиотеки скиллов Hermes.\n---\n\n"
            f"Скилл доступен в общей библиотеке: `skill_view(name='{s}')`.\n",
            encoding="utf-8")
    print(f"скиллы подключены: {', '.join(spec['skills'])}")

    added = tm.add_worker_to_team(team, name, project=project)
    if isinstance(added, dict) and added.get("error"):
        print("в команду не добавлен:", added["error"][:200])
        return 1
    print(f"добавлен в команду {team}" + (f", проект {project}" if project else ""))

    # Telegram-токен из .env профиля убираем: один бот — один профиль.
    env = pathlib.Path.home() / ".hermes" / "profiles" / name / ".env"
    if env.is_file():
        import re
        kept = [l for l in env.read_text(encoding="utf-8").splitlines(True)
                if not re.match(r"\s*TELEGRAM_(BOT_TOKEN|ALLOWED_USERS|HOME_CHAT)", l)]
        env.write_text("".join(kept), encoding="utf-8")
        env.chmod(0o600)
        print("Telegram-токен из .env профиля убран")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s_show = sub.add_parser("show")
    s_show.add_argument("name")
    s_inst = sub.add_parser("install")
    s_inst.add_argument("name")
    s_inst.add_argument("--team", required=True)
    s_inst.add_argument("--project", default=None)
    a = ap.parse_args()
    if a.cmd == "list":
        return cmd_list()
    if a.cmd == "show":
        return cmd_show(a.name)
    return cmd_install(a.name, a.team, a.project)


if __name__ == "__main__":
    sys.exit(main())
