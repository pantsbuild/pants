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
  """Timeout generator

      with Timeout(seconds):
        try:
          <do stuff>
        except KeyboardInterrupt:
          <handle timeout>

      If seconds is None or 0, then the there is no timeout
  """

  def __init__(self, seconds):
    if seconds:
      self._timer = threading.Timer(seconds, self._handle_timeout)
    else:
      self._timer = None

  def _handle_timeout(self):
    sys.stderr.flush()  # Python 3 stderr is likely buffered.
    thread.interrupt_main()  # raises KeyboardInterrupt

  def __enter__(self):
    if self._timer is not None:
      self._timer.start()

  def __exit__(self, type_, value, traceback):
    if type_ is KeyboardInterrupt:
      raise TimeoutReached
    elif self._timer is not None:
      self._timer.cancel()
