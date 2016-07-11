# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import sys

from twitter.common.collections import OrderedSet

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.project_tree_factory import get_project_tree
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.bin.engine_initializer import EngineInitializer
from pants.bin.repro import Reproducer
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.mutable_build_graph import MutableBuildGraph
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.java.nailgun_executor import NailgunProcessGroup
from pants.pantsd.subsystem.pants_daemon_launcher import PantsDaemonLauncher
from pants.reporting.reporting import Reporting
from pants.source.source_root import SourceRootConfig
from pants.task.task import QuietTaskMixin
from pants.util.filtering import create_filters, wrap_filters


logger = logging.getLogger(__name__)


class GoalRunnerFactory(object):
  def __init__(self, root_dir, options, build_config, run_tracker, reporting, build_graph=None,
               exiter=sys.exit):
    """
    :param str root_dir: The root directory of the pants workspace (aka the "build root").
    :param Options options: The global, pre-initialized Options instance.
    :param BuildConfiguration build_config: A pre-initialized BuildConfiguration instance.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param Reporting reporting: The global, pre-initialized Reporting instance.
    :param BuildGraph build_graph: A BuildGraph instance (for graph reuse, optional).
    :param func exiter: A function that accepts an exit code value and exits (for tests, Optional).
    """
    self._root_dir = root_dir
    self._options = options
    self._build_config = build_config
    self._run_tracker = run_tracker
    self._reporting = reporting
    self._exiter = exiter

    self._goals = []
    self._targets = []
    self._requested_goals = self._options.goals
    self._target_specs = self._options.target_specs
    self._help_request = self._options.help_request

    self._global_options = options.for_global_scope()
    self._tag = self._global_options.tag
    self._fail_fast = self._global_options.fail_fast
    self._explain = self._global_options.explain
    self._kill_nailguns = self._global_options.kill_nailguns

    self._build_file_parser = BuildFileParser(self._build_config, self._root_dir)
    build_ignore_patterns = self._global_options.ignore_patterns or []
    self._address_mapper = BuildFileAddressMapper(
      self._build_file_parser,
      get_project_tree(self._global_options),
      build_ignore_patterns,
      exclude_target_regexps=self._global_options.exclude_target_regexp
    )
    self._build_graph = self._select_buildgraph(self._global_options.enable_v2_engine,
                                                self._global_options.pants_ignore,
                                                build_graph)

  def _select_buildgraph(self, use_engine, path_ignore_patterns, cached_buildgraph=None):
    """Selects a BuildGraph to use then constructs and returns it.

    :param bool use_engine: Whether or not to use the v2 engine to construct the BuildGraph.
    :param list path_ignore_patterns: The path ignore patterns from `--pants-ignore`.
    :param LegacyBuildGraph cached_buildgraph: A cached graph to reuse, if available.
    """
    if cached_buildgraph is not None:
      return cached_buildgraph
    elif use_engine:
      root_specs = EngineInitializer.parse_commandline_to_spec_roots(options=self._options,
                                                                     build_root=self._root_dir)
      graph_helper = EngineInitializer.setup_legacy_graph(path_ignore_patterns)
      return graph_helper.create_graph(root_specs)
    else:
      return MutableBuildGraph(self._address_mapper)

  def _expand_goals(self, goals):
    """Check and populate the requested goals for a given run."""
    for goal in goals:
      try:
        self._address_mapper.resolve_spec(goal)
        logger.warning("Command-line argument '{0}' is ambiguous and was assumed to be "
                       "a goal. If this is incorrect, disambiguate it with ./{0}.".format(goal))
      except AddressLookupError:
        pass

    if self._help_request:
      help_printer = HelpPrinter(self._options)
      result = help_printer.print_help()
      self._exiter(result)

    self._goals.extend([Goal.by_name(goal) for goal in goals])

  def _expand_specs(self, spec_strs, fail_fast):
    """Populate the BuildGraph and target list from a set of input specs."""
    with self._run_tracker.new_workunit(name='parse', labels=[WorkUnitLabel.SETUP]):
      def filter_for_tag(tag):
        return lambda target: tag in map(str, target.tags)

      tag_filter = wrap_filters(create_filters(self._tag, filter_for_tag))

      # Parse all specs into unique Spec objects.
      spec_parser = CmdLineSpecParser(self._root_dir)
      specs = OrderedSet()
      for spec_str in spec_strs:
        specs.add(spec_parser.parse_spec(spec_str))

      # Then scan them to generate unique Addresses.
      for address in self._build_graph.inject_specs_closure(specs, fail_fast):
        target = self._build_graph.get_target(address)
        if tag_filter(target):
          self._targets.append(target)

  def _maybe_launch_pantsd(self):
    """Launches pantsd if configured to do so."""
    if self._global_options.enable_pantsd:
      # Avoid runtracker output if pantsd is disabled. Otherwise, show up to inform the user its on.
      with self._run_tracker.new_workunit(name='pantsd', labels=[WorkUnitLabel.SETUP]):
        pantsd_launcher = PantsDaemonLauncher.Factory.global_instance().create(EngineInitializer)
        pantsd_launcher.maybe_launch()

  def _is_quiet(self):
    return any(goal.has_task_of_type(QuietTaskMixin) for goal in self._goals) or self._explain

  def _setup_context(self):
    self._maybe_launch_pantsd()

    with self._run_tracker.new_workunit(name='setup', labels=[WorkUnitLabel.SETUP]):
      self._expand_goals(self._requested_goals)
      self._expand_specs(self._target_specs, self._fail_fast)

      # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
      self._run_tracker.run_info.add_scm_info()

      # Update the Reporting settings now that we have options and goal info.
      invalidation_report = self._reporting.update_reporting(self._global_options,
                                                             self._is_quiet(),
                                                             self._run_tracker)

      context = Context(options=self._options,
                        run_tracker=self._run_tracker,
                        target_roots=self._targets,
                        requested_goals=self._requested_goals,
                        build_graph=self._build_graph,
                        build_file_parser=self._build_file_parser,
                        address_mapper=self._address_mapper,
                        invalidation_report=invalidation_report)

    return context, invalidation_report

  def setup(self):
    context, invalidation_report = self._setup_context()
    return GoalRunner(context=context,
                      goals=self._goals,
                      kill_nailguns=self._kill_nailguns,
                      run_tracker=self._run_tracker,
                      invalidation_report=invalidation_report,
                      exiter=self._exiter)


class GoalRunner(object):
  """Lists installed goals or else executes a named goal."""

  Factory = GoalRunnerFactory

  def __init__(self, context, goals, run_tracker, invalidation_report, kill_nailguns,
               exiter=sys.exit):
    """
    :param Context context: The global, pre-initialized Context as created by GoalRunnerFactory.
    :param list[Goal] goals: The list of goals to act on.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param InvalidationReport invalidation_report: An InvalidationReport instance (Optional).
    :param bool kill_nailguns: Whether or not to kill nailguns after the run.
    :param func exiter: A function that accepts an exit code value and exits (for tests, Optional).
    """
    self._context = context
    self._goals = goals
    self._run_tracker = run_tracker
    self._invalidation_report = invalidation_report
    self._kill_nailguns = kill_nailguns
    self._exiter = exiter

  @classmethod
  def subsystems(cls):
    # Subsystems used outside of any task.
    return {SourceRootConfig, Reporting, Reproducer, RunTracker, PantsDaemonLauncher.Factory}

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

    if self._invalidation_report:
      self._invalidation_report.report()

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
