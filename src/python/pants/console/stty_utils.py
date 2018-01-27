# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys
import termios
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
    try:
      self._tty_flags = termios.tcgetattr(sys.stdin.fileno())
    except termios.error as e:
      logger.debug('masking tcgetattr exception: {!r}'.format(e))

  def restore_tty_flags(self):
    if self._tty_flags:
      try:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, self._tty_flags)
      except termios.error as e:
        logger.debug('masking tcsetattr exception: {!r}'.format(e))
