"""Fon vazifalari: `asyncio.create_task` natijasini saqlab turamiz, aks holda
GC ularni ish tugamasdan yo'q qilib yuborishi mumkin."""
from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

log = logging.getLogger("bg")
_TASKS: set[asyncio.Task] = set()


def _done(task: asyncio.Task) -> None:
    _TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.error("fon vazifasi yiqildi: %r", task.exception())


def spawn(coro: Coroutine) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_done)
    return task
