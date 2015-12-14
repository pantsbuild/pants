# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import thread
import threading


class TimeoutReached(Exception):
  def __init__(self, seconds):
    super(TimeoutReached, self).__init__("Timeout of {} seconds reached".format(seconds))


class Timeout(object):
  """Timeout generator. If seconds is None or 0, then the there is no timeout.

    try:
      with Timeout(seconds):
        <do stuff>
    except TimeoutReached:
      <handle timeout>
  """

  def __init__(self, seconds, abort_handler=lambda: None, threading_timer=threading.Timer):

    # self._triggered is not protected by a mutex because boolean set/get is atomic in all the Python
    # implementations we care about.
    self._triggered = False
    self._seconds = seconds
    self._abort_handler = abort_handler

    if self._seconds:
      self._timer = threading_timer(self._seconds, self._handle_timeout)
    else:
      self._timer = None

  def _handle_timeout(self):
    self._triggered = True
    self._abort_handler()

  def __enter__(self):
    if self._timer is not None:
      self._timer.start()

  def __exit__(self, type_, value, traceback):
    """If triggered, raise TimeoutReached.

    Rather than converting a KeyboardInterrupt to TimeoutReached here, we just check self._triggered,
    which helps us in the case where the thread we are trying to timeout isn't the main thread. Of
    course in that case the executing doesn't get interrupted at the appropriate time, but at least
    the exception still gets raised.
    """
    if self._triggered:
      raise TimeoutReached(self._seconds)

    elif self._timer is not None:
      self._timer.cancel()
