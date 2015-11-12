# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
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
