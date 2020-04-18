# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Optional


class StreamingWorkunitHandler:
    """StreamingWorkunitHandler's job is to periodically call each registered callback function with
    the following kwargs:

    workunits: Tuple[Dict[str, str], ...] - the workunit data itself
    finished: bool - this will be set to True when the last chunk of workunit data is reported to the callback
    """

    def __init__(
        self, scheduler: Any, callbacks: Iterable[Callable], report_interval_seconds: float
    ):
        self.scheduler = scheduler
        self.report_interval = report_interval_seconds
        self.callbacks = callbacks
        self._thread_runner: Optional[_InnerHandler] = None

    def start(self) -> None:
        if self.callbacks:
            self._thread_runner = _InnerHandler(
                self.scheduler, self.callbacks, self.report_interval
            )
            self._thread_runner.start()

    def end(self) -> None:
        if self._thread_runner:
            self._thread_runner.join()

        # After stopping the thread, poll workunits one last time to make sure
        # we report any workunits that were added after the last time the thread polled.
        workunits = self.scheduler.poll_workunits()
        for callback in self.callbacks:
            callback(
                workunits=workunits["completed"],
                started_workunits=workunits["started"],
                finished=True,
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
    def __init__(self, scheduler: Any, callbacks: Iterable[Callable], report_interval: float):
        super().__init__(daemon=True)
        self.scheduler = scheduler
        self.stop_request = threading.Event()
        self.report_interval = report_interval
        self.callbacks = callbacks

    def run(self):
        while not self.stop_request.isSet():
            workunits = self.scheduler.poll_workunits()
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
