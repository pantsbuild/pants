# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import os
import sys
import traceback

from pants.base.build_environment import get_buildroot, pants_version
from pants.bin.goal_runner import GoalRunner


_LOG_EXIT_OPTION = '--log-exit'
_VERSION_OPTION = '--version'
_PRINT_EXCEPTION_STACKTRACE = '--print-exception-stacktrace'


def _do_exit(result=0, msg=None, out=sys.stderr):
  if msg:
    print(msg, file=out)
  if _LOG_EXIT_OPTION in sys.argv and result == 0:
    print("\nSUCCESS\n")
  sys.exit(result)


def _exit_and_fail(msg=None):
  _do_exit(result=1, msg=msg)


def _unhandled_exception_hook(exception_class, exception, tb):
  msg = ''
  if _PRINT_EXCEPTION_STACKTRACE in sys.argv:
    msg = '\nException caught:\n' + ''.join(traceback.format_tb(tb))
  if str(exception):
    msg += '\nException message: %s\n' % str(exception)
  else:
    msg += '\nNo specific exception message.\n'
  # TODO(Jin Feng) Always output the unhandled exception details into a log file.
  _exit_and_fail(msg)


def _run():
  # Place the registration of the unhandled exception hook as early as possible in the code.
  sys.excepthook = _unhandled_exception_hook

  logging.basicConfig()
  version = pants_version()
  if len(sys.argv) == 2 and sys.argv[1] == _VERSION_OPTION:
    _do_exit(msg=version, out=sys.stdout)

  root_dir = get_buildroot()
  if not os.path.exists(root_dir):
    _exit_and_fail('PANTS_BUILD_ROOT does not point to a valid path: %s' % root_dir)

  goal_runner = GoalRunner(root_dir)
  goal_runner.setup()
  result = goal_runner.run()
  _do_exit(result)

def main():
  try:
    _run()
  except KeyboardInterrupt:
    _exit_and_fail('Interrupted by user.')

if __name__ == '__main__':
  main()
