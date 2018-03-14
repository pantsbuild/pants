# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_environment import get_buildroot
from pants.bin.goal_runner import GoalRunner
from pants.bin.repro import Reproducer
from pants.goal.run_tracker import RunTracker
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.reporting.reporting import Reporting
from pants.util.contextutil import hard_exit_handler, maybe_profiled


class LocalPantsRunner(object):
  """Handles a single pants invocation running in the process-local context."""

  def __init__(self, exiter, args, env, target_roots=None, daemon_build_graph=None,
               options_bootstrapper=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (e.g. sys.argv) for this run.
    :param dict env: The environment (e.g. os.environ) for this run.
    :param TargetRoots target_roots: The `TargetRoots` for this run.
    :param BuildGraph daemon_build_graph: A BuildGraph instance for graph reuse (optional).
    :param OptionsBootstrapper options_bootstrapper: An optional existing OptionsBootstrapper.
    """
    self._exiter = exiter
    self._args = args
    self._env = env
    self._target_roots = target_roots
    self._daemon_build_graph = daemon_build_graph
    self._options_bootstrapper = options_bootstrapper
    self._preceding_graph_size = -1
    self._run_start_time = None

  def set_preceding_graph_size(self, size):
    self._preceding_graph_size = size

  def set_start_time(self, start_time):
    self._run_start_time = start_time

  def run(self):
    profile_path = self._env.get('PANTS_PROFILE')
    with hard_exit_handler(), maybe_profiled(profile_path):
      self._run()

  def _run(self):
    # Bootstrap options and logging.
    options_bootstrapper = self._options_bootstrapper or OptionsBootstrapper(env=self._env,
                                                                             args=self._args)
    options, build_config = OptionsInitializer(options_bootstrapper, exiter=self._exiter).setup()
    global_options = options.for_global_scope()

    # Apply exiter options.
    self._exiter.apply_options(options)

    # Option values are usually computed lazily on demand,
    # but command line options are eagerly computed for validation.
    for scope in options.scope_to_flags.keys():
      options.for_scope(scope)

    # Verify the configs here.
    if global_options.verify_config:
      options_bootstrapper.verify_configs_against_options(options)

    # Launch RunTracker as early as possible (just after Subsystem options are initialized).
    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()
    reporting.initialize(run_tracker, self._run_start_time)

    try:
      # Determine the build root dir.
      root_dir = get_buildroot()

      # Capture a repro of the 'before' state for this build, if needed.
      repro = Reproducer.global_instance().create_repro()
      if repro:
        repro.capture(run_tracker.run_info.get_as_dict())

      # Record the preceding product graph size.
      run_tracker.pantsd_stats.set_preceding_graph_size(self._preceding_graph_size)

      # Setup and run GoalRunner.
      goal_runner = GoalRunner.Factory(root_dir,
                                       options,
                                       build_config,
                                       run_tracker,
                                       reporting,
                                       self._target_roots,
                                       self._daemon_build_graph,
                                       self._exiter).setup()

      goal_runner_result = goal_runner.run()

      if repro:
        # TODO: Have Repro capture the 'after' state (as a diff) as well?
        repro.log_location_of_repro_file()
    finally:
      run_tracker_result = run_tracker.end()

    # Take the exit code with higher abs value in case of negative values.
    final_exit_code = goal_runner_result if abs(goal_runner_result) > abs(run_tracker_result) else run_tracker_result
    self._exiter.exit(final_exit_code)
