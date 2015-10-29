# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
import traceback
from abc import abstractmethod

from colors import green

from pants.base.build_environment import get_buildroot
from pants.bin.goal_runner import GoalRunner, OptionsInitializer, ReportingInitializer
from pants.bin.repro import Reproducer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.meta import AbstractClass


class PantsRunner(AbstractClass):
  """An abstract class for implementing different methods/modes of running pants."""

  @abstractmethod
  def run():
    """Executes the runner."""


class Exiter(object):
  def __init__(self):
    # Since we have some exit paths that run via the sys.excepthook,
    # symbols we use can become garbage collected before we use them; ie:
    # we can find `sys` and `traceback` are `None`.  As a result we capture
    # all symbols we need here to ensure we function in excepthook context.
    # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
    self._exit = sys.exit
    self._format_tb = traceback.format_tb
    self._should_print_backtrace = True

  def __call__(self, *args, **kwargs):
    """Map class calls to self.exit() to support sys.exit() fungibility."""
    return self.exit(*args, **kwargs)

  def apply_options(self, options):
    self._should_print_backtrace = options.for_global_scope().print_exception_stacktrace

  def exit(self, result=0, msg=None, out=sys.stderr):
    if msg:
      print(msg, file=out)
    self._exit(result)

  def exit_and_fail(self, msg=None):
    self.exit(result=1, msg=msg)

  def unhandled_exception_hook(self, exception_class, exception, tb):
    msg = ''
    if self._should_print_backtrace:
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


class LocalPantsRunner(PantsRunner):
  """Handles a single pants invocation running in the process-local context."""

  def __init__(self, exiter, args=None, env=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (sys.argv) for this run. (Optional, default: sys.argv)
    :param dict env: The environment for this run. (Optional, default: os.environ)
    """
    self.exiter = exiter
    self.args = args or sys.argv
    self.env = env or os.environ
    self.profile_path = self.env.get('PANTS_PROFILE')

  def _maybe_profiled(self, runner):
    """Run with profiling, if requested."""
    if self.profile_path:
      import cProfile
      profiler = cProfile.Profile()
      try:
        profiler.runcall(runner)
      finally:
        profiler.dump_stats(self.profile_path)
        print('\nDumped profile data to {}'.format(self.profile_path))
        view_cmd = green('gprof2dot -f pstats {path} | dot -Tpng -o {path}.png && open {path}.png'
                         .format(path=self.profile_path))
        print('Use, e.g., {} to render and view.'.format(view_cmd))
    else:
      runner()

  def run(self):
    self._maybe_profiled(self._run)

  def _run(self):
    # Bootstrap options and logging.
    options_bootstrapper = OptionsBootstrapper(env=self.env, args=self.args)
    options, build_config = OptionsInitializer(options_bootstrapper, exiter=self.exiter).setup()

    # Apply exiter options.
    self.exiter.apply_options(options)

    # Launch RunTracker as early as possible (just after Subsystem options are initialized).
    run_tracker, reporting = ReportingInitializer().setup()

    try:
      # Determine the build root dir.
      root_dir = get_buildroot()

      # Capture a repro of the 'before' state for this build, if needed.
      repro = Reproducer.global_instance().create_repro()
      if repro:
        repro.capture(run_tracker.run_info.get_as_dict())

      # Setup and run GoalRunner.
      goal_runner = GoalRunner.Factory(root_dir,
                                       options,
                                       build_config,
                                       run_tracker,
                                       reporting,
                                       exiter=self.exiter).setup()

      result = goal_runner.run()

      if repro:
        # TODO: Have Repro capture the 'after' state (as a diff) as well?
        repro.log_location_of_repro_file()
    finally:
      run_tracker.end()

    self.exiter.exit(result)
