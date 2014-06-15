# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple


class Reporter(object):
  """Formats and emits reports.

  Subclasses implement the callback methods, to provide specific reporting
  functionality, e.g., to console or to browser.
  """

  # Generic reporting settings.
  #   log_level: Display log messages up to this level.
  #   subsettings: subclass-specific settings.
  Settings = namedtuple('Settings', ['log_level'])

  def __init__(self, run_tracker, settings):
    self.run_tracker = run_tracker
    self.settings = settings

  def open(self):
    """Begin the report."""
    pass

  def close(self):
    """End the report."""
    pass

  def start_workunit(self, workunit):
    """A new workunit has started."""
    pass

  def end_workunit(self, workunit):
    """A workunit has finished."""
    pass

  def handle_log(self, workunit, level, *msg_elements):
    """Handle a message logged by pants code.

    level: One of the constants above.

    Each element in msg_elements is either a message or a (message, detail) pair.
    A subclass must show the message, but may choose to show the detail in some
    sensible way (e.g., when the message text is clicked on in a browser).

    This convenience implementation filters by log level and then delegates to do_handle_log.
    """
    if level <= self.settings.log_level:
      self.do_handle_log(workunit, level, *msg_elements)

  def do_handle_log(self, workunit, level, *msg_elements):
    """Handle a message logged by pants code, after it's passed the log level check."""
    pass

  def handle_output(self, workunit, label, s):
    """Handle output captured from an invoked tool (e.g., javac).

    workunit: The innermost WorkUnit in which the tool was invoked.
    label: Classifies the output e.g., 'stdout' for output captured from a tool's stdout or
           'debug' for debug output captured from a tool's logfiles.
    s: The content captured.
    """
    pass

  def is_under_main_root(self, workunit):
    """Is the workunit running under the main thread's root."""
    return self.run_tracker.is_under_main_root(workunit)
