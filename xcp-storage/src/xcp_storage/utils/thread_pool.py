# Copyright (C) 2026  Vates SAS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import threading
from types import TracebackType

import xcp_storage.log as log

from xcp_storage.typing import (
    Any,
    Callable,
    Optional,
    override,
    Set,
    Type,
)

# ==============================================================================

class ThreadPoolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

class ThreadPoolNoWorkerError(ThreadPoolError):
    def __init__(self) -> None:
        super().__init__("No worker available.")

# ------------------------------------------------------------------------------

class ThreadPool:
    class _Worker(threading.Thread):
        def __init__(self, pool: "ThreadPool") -> None:
            super().__init__(daemon=True)
            self._pool: Optional[ThreadPool] = pool
            self._running = True
            self._task: Optional[Callable[[], Any]] = None
            self._event_task_changed = threading.Event()

        def set_task(self, task: Callable[[], Any]) -> None:
            self._task = task
            self._event_task_changed.set()

        def stop(self) -> None:
            self._running = False
            self._event_task_changed.set()

        @override
        def run(self) -> None:
            assert self._pool

            while self._running:
                self._event_task_changed.wait()
                self._event_task_changed.clear()

                if not self._running:
                    break

                assert self._task, "Task must be valid."
                try:
                    self._task()
                except Exception as e:
                    log.error(f"Unhandled thread pool exception: `{e}`.")

                self._task = None
                self._pool._handle_finished_task(self) # noqa: SLF001

            self._pool = None

    def __init__(self, min_worker_count: int, max_worker_count: int) -> None:
        if min_worker_count < 0:
            min_worker_count = 0
        max_worker_count = max(min_worker_count, max_worker_count, 1)

        self._running = True
        self._min_worker_count = min_worker_count
        self._max_worker_count = max_worker_count
        self._free_workers: Set[ThreadPool._Worker] = set()
        self._busy_workers: Set[ThreadPool._Worker] = set()

        self._free_workers_changed = threading.Event()

        self._lock = threading.Lock()

        for _ in range(self._min_worker_count):
            worker = self._Worker(self)
            worker.start()
            self._free_workers.add(worker)

    def __enter__(self) -> "ThreadPool":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType]
    ) -> None:
        self.stop()

    def stop(self) -> None:
        # Must be called by creator thread of this thread pool.
        with self._lock:
            if not self._running:
                return
            self._running = False

        workers = list(self._busy_workers) + list(self._free_workers)
        for worker in workers:
            worker.stop()

        self._free_workers.clear()
        self._busy_workers.clear()

        for worker in workers:
            worker.join(timeout=0.5)

    def add_task(self, task: Callable[[], Any], wait: bool = True) -> None:
        while True:
            try:
                self._add_task(task)
                return
            except ThreadPoolNoWorkerError:
                if not wait:
                    raise
                self._free_workers_changed.wait()
                self._free_workers_changed.clear()

    def _add_task(self, task: Callable[[], Any]) -> None:
        with self._lock:
            if not self._running:
                raise ThreadPoolError("Thread pool is not running.")

            if self._free_workers:
                worker = self._free_workers.pop()
            elif len(self._busy_workers) + len(self._free_workers) < self._max_worker_count:
                worker = self._Worker(self)
                worker.start()
            else:
                raise ThreadPoolNoWorkerError()

            self._busy_workers.add(worker)

        worker.set_task(task)

    def _handle_finished_task(self, worker: _Worker) -> None:
        with self._lock:
            if self._running:
                self._busy_workers.remove(worker)
                self._free_workers.add(worker)
