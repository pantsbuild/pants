# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys
import termios
import tty
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class STTYSettings(object):
  """Saves/restores stty settings, e.g., during REPL execution."""

  @classmethod
  @contextmanager
  def preserved(cls):
    """Run potentially stty-modifying operations, e.g., REPL execution, in this contextmanager."""
    inst = cls()
    inst.save_tty_flags()
    try:
      yield
    finally:
      inst.restore_tty_flags()

  def __init__(self):
    self._tty_flags = None

  def save_tty_flags(self):
    # N.B. `stty(1)` operates against stdin.
    self._tty_flags = tty.tcgetattr(sys.stdin.fileno())

  def restore_tty_flags(self):
    if self._tty_flags:
      try:
        tty.tcsetattr(sys.stdin.fileno(), tty.TCSANOW, self._tty_flags)
      except termios.error as e:
        # N.B. This can happen if e.g. sys.stdin is closed (EBADF) etc and
        # shouldn't necessarily result in a pants error.
        logger.debug('masking tcsetattr exception: {!r}'.format(e))
