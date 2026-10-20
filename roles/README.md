# Шаблоны ролей

Роли устанавливаются скриптом `scripts/make_role.py`:

```bash
python3 ~/.hermes/scripts/make_role.py list
python3 ~/.hermes/scripts/make_role.py install leads --team site-factory --project demo-sites
```

Роль = профиль Hermes + SOUL.md + стартовые скиллы.

| Роль | Роль в Agora | Скиллы |
|---|---|---|
| `leads` | researcher | business-site-presence-check, site-own-seo-first-visitor-is-weeks |
| `copy` | writer | sepia, humanizer |
| `designer` | developer | popular-web-designs, claude-design, demo-page-visual-gate |
| `watcher` | devops | watcher-output-file-hygiene, host-load-attribution-before-self-limiting |
| `sourcer` | sourcer | bounty-payout-rail-truth-table, agent-task-claim-to-payout |

Полное описание ролей и их правил — `docs/roles.md`.
