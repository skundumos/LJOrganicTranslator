"""Job runner abstraction. BackgroundTaskRunner schedules async work without blocking the
request handler; later swap to RQ/Celery by implementing JobRunner.submit.

Critical: in Python 3.14, asyncio.get_event_loop() raises RuntimeError when called from a
non-main thread that has no loop. We must always check for a running loop first, and fall
back to asyncio.run() (which creates a fresh loop) when we're not inside one.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger("ad_localizer.runner")


class JobRunner(ABC):
    @abstractmethod
    def submit(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None: ...


class BackgroundTaskRunner(JobRunner):
    """Fire-and-forget runner for the FastAPI MVP.

    - In an async context (running event loop): schedules the coroutine on that loop and
      retains a strong reference so it doesn't get garbage-collected.
    - In a sync/threadpool context (no running loop): spawns a daemon thread that runs the
      coroutine in its own asyncio.run() loop. This keeps the caller non-blocking.
    """

    _tasks: set[asyncio.Task] = set()

    def submit(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            task = loop.create_task(self._wrap(coro_factory))
            self._tasks.add(task)
            task.add_done_callback(self._on_done)
            return

        # No running loop — run the coroutine in a dedicated daemon thread so we don't block.
        def _run_in_thread() -> None:
            try:
                asyncio.run(self._wrap(coro_factory))
            except Exception:
                log.exception("Background thread failed")

        thread = threading.Thread(target=_run_in_thread, daemon=True, name="JobRunner")
        thread.start()

    @staticmethod
    async def _wrap(coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        try:
            await coro_factory()
        except Exception:
            log.exception("Background task failed")

    @classmethod
    def _on_done(cls, task: asyncio.Task) -> None:
        cls._tasks.discard(task)
        exc = task.exception()
        if exc:
            log.exception("Task exception", exc_info=exc)


runner: JobRunner = BackgroundTaskRunner()
