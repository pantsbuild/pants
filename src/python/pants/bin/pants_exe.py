# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
import traceback
import warnings

from colors import green


# We want to present warnings to the user, set this up before importing any of our own code,
# to ensure all deprecation warnings are seen, including module deprecations.
# The "default" action displays a warning for a particular file and line number exactly once.
# See https://docs.python.org/2/library/warnings.html#the-warnings-filter for the complete list.
warnings.simplefilter('default', DeprecationWarning)

from pants.base.build_environment import get_buildroot  # isort:skip
from pants.bin.goal_runner import GoalRunner, OptionsInitializer, ReportingInitializer  # isort:skip
from pants.bin.repro import Reproducer  # isort:skip


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
      msg = '\nException caught: ({})\n{}'.format(type(exception), ''.join(self._format_tb(tb)))
    if str(exception):
      msg += '\nException message: {}\n'.format(exception)
    else:
      msg += '\nNo specific exception message.\n'
    # TODO(Jin Feng) Always output the unhandled exception details into a log file.
    self.exit_and_fail(msg)

  def set_except_hook(self):
    # Call the registration of the unhandled exception hook as early as possible in the code.
    sys.excepthook = self.unhandled_exception_hook


def _run(exiter):
  # Bootstrap options and logging.
  options, build_config = OptionsInitializer().setup()

  # Apply exiter options.
  exiter.apply_options(options)

  # Launch RunTracker as early as possible (just after Subsystem options are initialized).
  run_tracker, reporting = ReportingInitializer().setup()

  # Determine the build root dir.
  root_dir = get_buildroot()

  # Capture a repro of the 'before' state for this build, if needed.
  repro = Reproducer.global_instance().create_repro()
  if repro:
    repro.capture(run_tracker.run_info.get_as_dict())

  # Set up and run GoalRunner.
  def run():
    goal_runner = GoalRunner.Factory(root_dir, options, build_config,
                                     run_tracker, reporting).setup()
    return goal_runner.run()

  # Run with profiling, if requested.
  profile_path = os.environ.get('PANTS_PROFILE')
  if profile_path:
    import cProfile
    profiler = cProfile.Profile()
    try:
      result = profiler.runcall(run)
    finally:
      profiler.dump_stats(profile_path)
      print('Dumped profile data to {}'.format(profile_path))
      view_cmd = green('gprof2dot -f pstats {path} | dot -Tpng -o {path}.png && '
                       'open {path}.png'.format(path=profile_path))
      print('Use, e.g., {} to render and view.'.format(view_cmd))
  else:
    result = run()

  if repro:
    # TODO: Have Repro capture the 'after' state (as a diff) as well?
    repro.log_location_of_repro_file()

  exiter.do_exit(result)


def main():
  exiter = _Exiter()
  exiter.set_except_hook()

  try:
    _run(exiter)
  except KeyboardInterrupt:
    exiter.exit_and_fail('Interrupted by user.')


if __name__ == '__main__':
  main()
