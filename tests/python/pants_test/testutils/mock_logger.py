# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys

from pants.reporting.report import Report


class MockLogger(object):
  """A standalone logger that writes to stderr.

  Useful for testing without requiring the full RunTracker reporting framework.
  """
  def __init__(self, level=Report.INFO):
    self._level = level

  def _maybe_log(self, level, *msg_elements):
    if level <= self._level:
      sys.stderr.write(''.join(msg_elements))

  def debug(self, *msg_elements): self._maybe_log(Report.DEBUG, *msg_elements)
  def info(self, *msg_elements): self._maybe_log(Report.INFO, *msg_elements)
  def warn(self, *msg_elements): self._maybe_log(Report.WARN, *msg_elements)
  def error(self, *msg_elements): self._maybe_log(Report.ERROR, *msg_elements)
  def fatal(self, *msg_elements): self._maybe_log(Report.FATAL, *msg_elements)
