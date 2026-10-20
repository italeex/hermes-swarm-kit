"""hermes-ops — плагин, дающий агентам инструменты изменения самого Hermes.

Загрузчик вызывает register(ctx); каждый инструмент получает ctx.register_tool.
Все ограничения (деньги, разрушение, журнал) соблюдаются внутри модуля.
"""
from __future__ import annotations

from pathlib import Path
import sys

_DIR = str(Path(__file__).resolve().parent)
if _DIR in sys.path:
    sys.path.remove(_DIR)
sys.path.insert(0, _DIR)

import hermes_ops  # noqa: E402


def register(ctx) -> None:
    hermes_ops.register(ctx)
