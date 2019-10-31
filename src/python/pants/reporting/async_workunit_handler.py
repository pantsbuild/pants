# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional


DEFAULT_REPORT_INTERVAL_SECONDS = 10


class AsyncWorkunitHandler:
  def __init__(self, scheduler: Any, callback: Optional[Callable], report_interval_seconds: float = DEFAULT_REPORT_INTERVAL_SECONDS):
    self.scheduler = scheduler
    self.report_interval = report_interval_seconds
    self.callback = callback
    self._thread_runner = None

  def start(self):
    self._thread_runner = _InnerHandler(self.scheduler, self.callback, self.report_interval)
    self._thread_runner.start()

  def end(self):
    if self._thread_runner:
      self._thread_runner.stop_request.set()

  @contextmanager
  def session(self) -> Iterator[None]:
    self.start()
    try:
      yield
    except Exception as e:
      self.end()
      raise e
    self.end()


class _InnerHandler(threading.Thread):
  def __init__(self, scheduler: Any, callback: Optional[Callable], report_interval: float):
    super(_InnerHandler, self).__init__()
    self.scheduler = scheduler
    self.stop_request = threading.Event()
    self.report_interval = report_interval
    self.callback = callback

  def run(self):
    while not self.stop_request.isSet():
      workunits = self.scheduler.poll_workunits()
      if self.callback:
        self.callback(workunits)
      self.stop_request.wait(timeout=self.report_interval)

  def join(self, timeout=None):
    self.stop_request.set()
    super(_InnerHandler, self).join(timeout)
