"""Job runner abstraction. BackgroundTaskRunner uses FastAPI BackgroundTasks for the MVP;
later swap to RQ/Celery by implementing JobRunner.submit.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger("ad_localizer.runner")


class JobRunner(ABC):
    @abstractmethod
    def submit(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None: ...


class BackgroundTaskRunner(JobRunner):
    def submit(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        loop = asyncio.get_event_loop()
        task = loop.create_task(self._wrap(coro_factory))
        task.add_done_callback(self._on_done)

    async def _wrap(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        try:
            await coro_factory()
        except Exception:
            log.exception("Background task failed")

    @staticmethod
    def _on_done(task: asyncio.Task) -> None:
        exc = task.exception()
        if exc:
            log.exception("Task exception", exc_info=exc)


runner: JobRunner = BackgroundTaskRunner()
