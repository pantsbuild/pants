# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from collections import namedtuple

from colors import red
from six import string_types

from pants.reporting.report import Report
from pants.reporting.reporter import Reporter


class QuietReporter(Reporter):
  """Squelched plaintext reporting, only prints errors."""
  Settings = namedtuple('Settings', Reporter.Settings._fields + ('color', ))

  def __init__(self, run_tracker, settings):
    Reporter.__init__(self, run_tracker, settings)

  def open(self):
    """Implementation of Reporter callback."""
    pass

  def close(self):
    """Implementation of Reporter callback."""
    pass

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    pass

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    pass

  def do_handle_log(self, workunit, level, *msg_elements):
    """Implementation of Reporter callback."""
    # If the element is a (msg, detail) pair, we ignore the detail. There's no
    # useful way to display it on the console.
    elements = [e if isinstance(e, string_types) else e[0] for e in msg_elements]
    msg = '\n' + ''.join(elements)
    if self.settings.color:
      msg = red(msg)
    self._emit(msg)

  def handle_output(self, workunit, label, s):
    """Implementation of Reporter callback."""
    pass

  def _emit(self, s):
    sys.stdout.write(s)

  def level_for_workunit(self, workunit, default_level):
    """Force the reporter to consider every workunit to be logging for level Report.ERROR"""
    return Report.ERROR
