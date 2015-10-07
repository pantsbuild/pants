# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import thread
import threading


class TimeoutReached(Exception):
  pass


class Timeout(object):
  """
  Timeout generator. If seconds is None or 0, then the there is no timeout.

    try:
      with Timeout(seconds):
        <do stuff>
    except TimeoutReached:
      <handle timeout>
  """

  def __init__(self, seconds):
    self._triggered = False

    if seconds:
      self._timer = threading.Timer(seconds, self._handle_timeout)
    else:
      self._timer = None

  def _handle_timeout(self):
    sys.stderr.flush()  # Python 3 stderr is likely buffered.
    self._triggered = True
    thread.interrupt_main()  # raises KeyboardInterrupt

  def __enter__(self):
    if self._timer is not None:
      self._timer.start()

  def __exit__(self, type_, value, traceback):
    """
    If triggered, raise TimeoutReached.

    Rather than converting a KeyboardInterrupt to TimeoutReached here, we just check self._triggered,
    which helps us in the case where the thread we are trying to timeout isn't the main thread. Of
    course in that case the executing doesn't get interrupted at the appropriate time, but at least
    the exception still gets raised.
    """
    if self._triggered:
      raise TimeoutReached
    elif self._timer is not None:
      self._timer.cancel()
