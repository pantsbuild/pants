# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import Queue
import threading


class Timeout(Exception): pass


def deadline(closure, timeout=1.0, daemon=True, propagate=True):
  """Run a closure with a timeout, raising an exception if the timeout is exceeded.

     :param func closure: function to be run
     :param float timeout: the amount of time to allow (in seconds)
     :param bool daemon: whether to run as a daemon thread or not
     :param bool propagate: whether to re-raise exceptions thrown by the closure
     :raises: `Timeout` if the timeout is hit.
  """
  if not isinstance(timeout, (float, int)):
    raise TypeError('timeout must be numeric')

  q = Queue.Queue(maxsize=1)

  class AnonymousThread(threading.Thread):
    def __init__(self):
      super(AnonymousThread, self).__init__()
      self.daemon = bool(daemon)

    def run(self):
      try:
        result = closure()
      except Exception as result:
        if not propagate:
          # Conform to standard behaviour of an exception being raised inside a Thread.
          raise result

      q.put(result)

  AnonymousThread().start()

  try:
    result = q.get(timeout=timeout)
  except Queue.Empty:
    raise Timeout("Timeout exceeded!")
  else:
    if propagate and isinstance(result, Exception):
      raise result
    else:
      return result


def until(closure, event):
  """Loop forever while executing a closure until a True condition is met or an event is set.

     :param func closure: conditional function to run
     :param threading.Event event: a threading.Event to signal termination
  """
  while 1:
    if closure():
      return True
    elif event.is_set():
      return False


def wait_until(closure, timeout):
  """Wait until a closure returns a True condition or until a timeout is hit.

     :param func closure: conditional function to run
     :param float timeout: a timeout (in seconds) before raising Timeout
     :raises: `Timeout` if the timeout is hit.
  """
  event = threading.Event()
  try:
    return deadline(functools.partial(until, closure, event), timeout)
  except Timeout:
    event.set()
    raise
