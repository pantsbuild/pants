# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.project_tree_factory import get_project_tree
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.bin.engine_initializer import EngineInitializer
from pants.bin.repro import Reproducer
from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.mutable_build_graph import MutableBuildGraph
from pants.engine.round_engine import RoundEngine
from pants.engine.subsystem.native import Native
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.init.pants_daemon_launcher import PantsDaemonLauncher
from pants.init.target_roots import TargetRoots
from pants.java.nailgun_executor import NailgunProcessGroup
from pants.reporting.reporting import Reporting
from pants.scm.subsystems.changed import Changed
from pants.source.source_root import SourceRootConfig
from pants.task.task import QuietTaskMixin
from pants.util.filtering import create_filters, wrap_filters


logger = logging.getLogger(__name__)


class GoalRunnerFactory(object):
  def __init__(self, root_dir, options, build_config, run_tracker, reporting,
               daemon_graph_helper=None, exiter=sys.exit):
    """
    :param str root_dir: The root directory of the pants workspace (aka the "build root").
    :param Options options: The global, pre-initialized Options instance.
    :param BuildConfiguration build_config: A pre-initialized BuildConfiguration instance.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param Reporting reporting: The global, pre-initialized Reporting instance.
    :param LegacyGraphHelper daemon_graph_helper: A LegacyGraphHelper instance for graph reuse. (Optional)
    :param func exiter: A function that accepts an exit code value and exits. (for tests, Optional)
    """
    self._root_dir = root_dir
    self._options = options
    self._build_config = build_config
    self._run_tracker = run_tracker
    self._reporting = reporting
    self._daemon_graph_helper = daemon_graph_helper
    self._exiter = exiter

    self._requested_goals = self._options.goals
    self._help_request = self._options.help_request
    self._build_file_parser = BuildFileParser(self._build_config, self._root_dir)
    self._build_graph = None
    self._address_mapper = None

    self._global_options = options.for_global_scope()
    self._tag = self._global_options.tag
    self._fail_fast = self._global_options.fail_fast
    self._explain = self._global_options.explain
    self._kill_nailguns = self._global_options.kill_nailguns

  def _handle_help(self, help_request):
    """Handle requests for `help` information."""
    if help_request:
      help_printer = HelpPrinter(self._options)
      result = help_printer.print_help()
      self._exiter(result)

  def _init_graph(self, use_engine, pants_ignore_patterns, build_ignore_patterns,
                  exclude_target_regexps, target_specs, workdir, graph_helper=None,
                  subproject_build_roots=None):
    """Determine the BuildGraph, AddressMapper and spec_roots for a given run.

    :param bool use_engine: Whether or not to use the v2 engine to construct the BuildGraph.
    :param list pants_ignore_patterns: The pants ignore patterns from '--pants-ignore'.
    :param list build_ignore_patterns: The build ignore patterns from '--build-ignore',
                                       applied during BUILD file searching.
    :param str workdir: The pants workdir.
    :param list exclude_target_regexps: Regular expressions for targets to be excluded.
    :param list target_specs: The original target specs.
    :param LegacyGraphHelper graph_helper: A LegacyGraphHelper to use for graph construction,
                                           if available. This would usually come from the daemon.
    :returns: A tuple of (BuildGraph, AddressMapper, spec_roots).
    """
    # N.B. Use of the daemon implies use of the v2 engine.
    if graph_helper or use_engine:
      # The daemon may provide a `graph_helper`. If that's present, use it for graph construction.
      if not graph_helper:
        native = Native.Factory.global_instance().create()
        native.set_panic_handler()
        graph_helper = EngineInitializer.setup_legacy_graph(
          pants_ignore_patterns,
          workdir,
          native=native,
          build_ignore_patterns=build_ignore_patterns,
          exclude_target_regexps=exclude_target_regexps,
          subproject_roots=subproject_build_roots,
          include_trace_on_error=self._options.for_global_scope().print_exception_stacktrace
        )

      target_roots = TargetRoots.create(options=self._options,
                                        build_root=self._root_dir,
                                        change_calculator=graph_helper.change_calculator)
      graph, address_mapper = graph_helper.create_build_graph(target_roots, self._root_dir,
                                                              include_trace_on_error=self._global_options.print_exception_stacktrace)
      return graph, address_mapper, target_roots.as_specs()
    else:
      spec_roots = TargetRoots.parse_specs(target_specs, self._root_dir)
      address_mapper = BuildFileAddressMapper(self._build_file_parser,
                                              get_project_tree(self._global_options),
                                              build_ignore_patterns,
                                              exclude_target_regexps,
                                              subproject_build_roots)
      return MutableBuildGraph(address_mapper), address_mapper, spec_roots

  def _determine_goals(self, requested_goals):
    """Check and populate the requested goals for a given run."""
    def is_quiet(goals):
      return any(goal.has_task_of_type(QuietTaskMixin) for goal in goals) or self._explain

    spec_parser = CmdLineSpecParser(self._root_dir)
    for goal in requested_goals:
      if self._address_mapper.is_valid_single_address(spec_parser.parse_spec(goal)):
        logger.warning("Command-line argument '{0}' is ambiguous and was assumed to be "
                       "a goal. If this is incorrect, disambiguate it with ./{0}.".format(goal))

    goals = [Goal.by_name(goal) for goal in requested_goals]
    return goals, is_quiet(goals)

  def _specs_to_targets(self, specs):
    """Populate the BuildGraph and target list from a set of input specs."""
    with self._run_tracker.new_workunit(name='parse', labels=[WorkUnitLabel.SETUP]):
      def filter_for_tag(tag):
        return lambda target: tag in map(str, target.tags)

      tag_filter = wrap_filters(create_filters(self._tag, filter_for_tag))

      def generate_targets(specs):
        for address in self._build_graph.inject_specs_closure(specs, self._fail_fast):
          target = self._build_graph.get_target(address)
          if tag_filter(target):
            yield target

    return list(generate_targets(specs))

  def _maybe_launch_pantsd(self, pantsd_launcher):
    """Launches pantsd if configured to do so."""
    if self._global_options.enable_pantsd:
      # Avoid runtracker output if pantsd is disabled. Otherwise, show up to inform the user its on.
      with self._run_tracker.new_workunit(name='pantsd', labels=[WorkUnitLabel.SETUP]):
        pantsd_launcher.maybe_launch()

  def _setup_context(self, pantsd_launcher):
    with self._run_tracker.new_workunit(name='setup', labels=[WorkUnitLabel.SETUP]):
      self._build_graph, self._address_mapper, spec_roots = self._init_graph(
        self._global_options.enable_v2_engine,
        self._global_options.pants_ignore,
        self._global_options.build_ignore,
        self._global_options.exclude_target_regexp,
        self._options.target_specs,
        self._global_options.pants_workdir,
        self._daemon_graph_helper,
        self._global_options.subproject_roots,
      )
      goals, is_quiet = self._determine_goals(self._requested_goals)
      target_roots = self._specs_to_targets(spec_roots)

      # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
      self._run_tracker.run_info.add_scm_info()

      # Update the Reporting settings now that we have options and goal info.
      invalidation_report = self._reporting.update_reporting(self._global_options,
                                                             is_quiet,
                                                             self._run_tracker)

      context = Context(options=self._options,
                        run_tracker=self._run_tracker,
                        target_roots=target_roots,
                        requested_goals=self._requested_goals,
                        build_graph=self._build_graph,
                        build_file_parser=self._build_file_parser,
                        address_mapper=self._address_mapper,
                        invalidation_report=invalidation_report,
                        pantsd_launcher=pantsd_launcher)
      return goals, context

  def setup(self):
    pantsd_launcher = PantsDaemonLauncher.Factory.global_instance().create(EngineInitializer)
    self._maybe_launch_pantsd(pantsd_launcher)
    self._handle_help(self._help_request)
    goals, context = self._setup_context(pantsd_launcher)
    return GoalRunner(context=context,
                      goals=goals,
                      run_tracker=self._run_tracker,
                      kill_nailguns=self._kill_nailguns,
                      exiter=self._exiter)


class GoalRunner(object):
  """Lists installed goals or else executes a named goal."""

  Factory = GoalRunnerFactory

  def __init__(self, context, goals, run_tracker, kill_nailguns, exiter=sys.exit):
    """
    :param Context context: The global, pre-initialized Context as created by GoalRunnerFactory.
    :param list[Goal] goals: The list of goals to act on.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param bool kill_nailguns: Whether or not to kill nailguns after the run.
    :param func exiter: A function that accepts an exit code value and exits (for tests, Optional).
    """
    self._context = context
    self._goals = goals
    self._run_tracker = run_tracker
    self._kill_nailguns = kill_nailguns
    self._exiter = exiter

  @classmethod
  def subsystems(cls):
    """Subsystems used outside of any task."""
    return {
      SourceRootConfig,
      Reporting,
      Reproducer,
      RunTracker,
      Changed.Factory,
      Native.Factory,
      PantsDaemonLauncher.Factory,
    }

  def _execute_engine(self):
    workdir = self._context.options.for_global_scope().pants_workdir
    if not workdir.endswith('.pants.d'):
      self._context.log.error('Pants working directory should end with \'.pants.d\', currently it is {}\n'
                              .format(workdir))
      return 1

    unknown_goals = [goal.name for goal in self._goals if not goal.ordered_task_names()]
    if unknown_goals:
      self._context.log.error('Unknown goal(s): {}\n'.format(' '.join(unknown_goals)))
      return 1

    engine = RoundEngine()
    result = engine.execute(self._context, self._goals)

    if self._context.invalidation_report:
      self._context.invalidation_report.report()

    return result

  def run(self):
    should_kill_nailguns = self._kill_nailguns

    try:
      result = self._execute_engine()
      if result:
        self._run_tracker.set_root_outcome(WorkUnit.FAILURE)
    except KeyboardInterrupt:
      self._run_tracker.set_root_outcome(WorkUnit.FAILURE)
      # On ctrl-c we always kill nailguns, otherwise they might keep running
      # some heavyweight compilation and gum up the system during a subsequent run.
      should_kill_nailguns = True
      raise
    except Exception:
      self._run_tracker.set_root_outcome(WorkUnit.FAILURE)
      raise
    finally:
      # Must kill nailguns only after run_tracker.end() is called, otherwise there may still
      # be pending background work that needs a nailgun.
      if should_kill_nailguns:
        # TODO: This is JVM-specific and really doesn't belong here.
        # TODO: Make this more selective? Only kill nailguns that affect state?
        # E.g., checkstyle may not need to be killed.
        NailgunProcessGroup().killall()

    return result
