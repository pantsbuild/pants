# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys
import traceback
import warnings

from pants.base.build_environment import get_buildroot, pants_version
from pants.bin.goal_runner import GoalRunner


class _Exiter(object):
  def __init__(self):
    # Since we have some exit paths that run via the sys.excepthook,
    # symbols we use can become garbage collected before we use them; ie:
    # we can find `sys` and `traceback` are `None`.  As a result we capture
    # all symbols we need here to ensure we function in excepthook context.
    # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
    self._exit = sys.exit
    self._format_tb = traceback.format_tb
    self._is_print_backtrace = True

  def apply_options(self, options):
    self._is_print_backtrace = options.for_global_scope().print_exception_stacktrace

  def do_exit(self, result=0, msg=None, out=sys.stderr):
    if msg:
      print(msg, file=out)
    self._exit(result)

  def exit_and_fail(self, msg=None):
    self.do_exit(result=1, msg=msg)

  def unhandled_exception_hook(self, exception_class, exception, tb):
    msg = ''
    if self._is_print_backtrace:
      msg = '\nException caught:\n' + ''.join(self._format_tb(tb))
    if str(exception):
      msg += '\nException message: {}\n'.format(exception)
    else:
      msg += '\nNo specific exception message.\n'
    # TODO(Jin Feng) Always output the unhandled exception details into a log file.
    self.exit_and_fail(msg)


def _run(exiter):
  # Place the registration of the unhandled exception hook as early as possible in the code.
  sys.excepthook = exiter.unhandled_exception_hook

  # We want to present warnings to the user, set this up early to ensure all warnings are seen.
  # The "default" action displays a warning for a particular file and line number exactly once.
  # See https://docs.python.org/2/library/warnings.html#the-warnings-filter for the complete action
  # list.
  warnings.simplefilter("default")

  # The GoalRunner will setup final logging below in `.setup()`, but span the gap until then.
  logging.basicConfig()
  # This routes the warnings we enabled above through our loggers instead of straight to stderr raw.
  logging.captureWarnings(True)

  root_dir = get_buildroot()
  if not os.path.exists(root_dir):
    exiter.exit_and_fail('PANTS_BUILD_ROOT does not point to a valid path: {}'.format(root_dir))

  goal_runner = GoalRunner(root_dir)
  goal_runner.setup()
  exiter.apply_options(goal_runner.options)
  result = goal_runner.run()
  exiter.do_exit(result)


def main():
  exiter = _Exiter()
  try:
    _run(exiter)
  except KeyboardInterrupt:
    exiter.exit_and_fail('Interrupted by user.')

if __name__ == '__main__':
  main()
