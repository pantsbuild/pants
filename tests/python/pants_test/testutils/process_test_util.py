# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import psutil


class ProcessStillRunning(AssertionError):
  """Raised when a process shouldn't be running but is."""


def assert_no_process_exists_by_command(name):
  """Asserts that no process exists for a given command with a helpful error."""
  for proc in psutil.process_iter():
    try:
      cmdline = proc.cmdline()
      if name in ''.join(cmdline):
        raise ProcessStillRunning(
          'a {} process was detected at PID {} (cmdline={})'.format(name, proc.pid, cmdline)
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass
