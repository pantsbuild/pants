# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence, Tuple

from pants.engine.fs import Digest
from pants.engine.internals.scheduler import SchedulerSession
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class StreamingWorkunitContext:
    _scheduler: SchedulerSession

    def digests_to_bytes(self, digests: Sequence[Digest]) -> Tuple[bytes]:
        """Given a list of Digest objects, return a list of the bytes corresponding to each of those
        Digests in sequence."""
        return self._scheduler.digests_to_bytes(digests)

    def ensure_remote_has_recursive(self, digests: Sequence[Digest]) -> None:
        """Invoke the internal ensure_remote_has_recursive function, which ensures that a remote
        ByteStore, if it exists, has a copy of the files fingerprinted by each Digest."""
        return self._scheduler.ensure_remote_has_recursive(digests)


class StreamingWorkunitHandler:
    """StreamingWorkunitHandler's job is to periodically call each registered callback function with
    the following kwargs:

    workunits: Tuple[Dict[str, str], ...] - the workunit data itself
    finished: bool - this will be set to True when the last chunk of workunit data is reported to the callback
    """

    def __init__(
        self,
        scheduler: Any,
        callbacks: Iterable[Callable],
        report_interval_seconds: float,
        max_workunit_verbosity: LogLevel = LogLevel.DEBUG,
    ):
        self.scheduler = scheduler
        self.report_interval = report_interval_seconds
        self.callbacks = callbacks
        self._thread_runner: Optional[_InnerHandler] = None
        # TODO(10092) The max verbosity should be a per-client setting, rather than a global setting.
        self.max_workunit_verbosity = max_workunit_verbosity

    def start(self) -> None:
        if self.callbacks:
            self._thread_runner = _InnerHandler(
                self.scheduler, self.callbacks, self.report_interval, self.max_workunit_verbosity
            )
            self._thread_runner.start()

    def end(self) -> None:
        if self._thread_runner:
            self._thread_runner.join()

        # After stopping the thread, poll workunits one last time to make sure
        # we report any workunits that were added after the last time the thread polled.
        workunits = self.scheduler.poll_workunits(self.max_workunit_verbosity)
        for callback in self.callbacks:
            callback(
                workunits=workunits["completed"],
                started_workunits=workunits["started"],
                finished=True,
                context=StreamingWorkunitContext(_scheduler=self.scheduler),
            )

    @contextmanager
    def session(self) -> Iterator[None]:
        try:
            self.start()
            yield
            self.end()
        except Exception as e:
            if self._thread_runner:
                self._thread_runner.join()
            raise e


class _InnerHandler(threading.Thread):
    def __init__(
        self,
        scheduler: Any,
        callbacks: Iterable[Callable],
        report_interval: float,
        max_workunit_verbosity: LogLevel,
    ):
        super().__init__(daemon=True)
        self.scheduler = scheduler
        self.stop_request = threading.Event()
        self.report_interval = report_interval
        self.callbacks = callbacks
        self.max_workunit_verbosity = max_workunit_verbosity

    def run(self):
        while not self.stop_request.isSet():
            workunits = self.scheduler.poll_workunits(self.max_workunit_verbosity)
            for callback in self.callbacks:
                callback(
                    workunits=workunits["completed"],
                    started_workunits=workunits["started"],
                    finished=False,
                )
            self.stop_request.wait(timeout=self.report_interval)

    def join(self, timeout=None):
        self.stop_request.set()
        super(_InnerHandler, self).join(timeout)
