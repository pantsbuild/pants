# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import sys

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.build_file_parser import BuildFileParser
from pants.engine.native import Native
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import EngineInitializer
from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.java.nailgun_executor import NailgunProcessGroup
from pants.option.arg_splitter import UnknownGoalHelp
from pants.option.ranked_value import RankedValue
from pants.task.task import QuietTaskMixin


logger = logging.getLogger(__name__)


class GoalRunnerFactory(object):
  def __init__(self, root_dir, options, build_config, run_tracker, reporting,
               target_roots=None, daemon_graph_helper=None, exiter=sys.exit):
    """
    :param str root_dir: The root directory of the pants workspace (aka the "build root").
    :param Options options: The global, pre-initialized Options instance.
    :param BuildConfiguration build_config: A pre-initialized BuildConfiguration instance.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param Reporting reporting: The global, pre-initialized Reporting instance.
    :param TargetRoots target_roots: A pre-existing `TargetRoots` object, if available.
    :param LegacyGraphSession daemon_graph_helper: A LegacyGraphSession instance for graph
                                                   reuse. (Optional)
    :param func exiter: A function that accepts an exit code value and exits. (for tests, Optional)
    """
    self._root_dir = root_dir
    self._options = options
    self._build_config = build_config
    self._run_tracker = run_tracker
    self._reporting = reporting
    self._target_roots = target_roots
    self._daemon_graph_helper = daemon_graph_helper
    self._exiter = exiter

    self._is_daemon_run = daemon_graph_helper is not None
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

  def _get_graph_helper(self):
    # The daemon may provide a `graph_helper`. If that's present, use it for graph construction.
    if self._daemon_graph_helper:
      return self._daemon_graph_helper

    native = Native.create(self._global_options)
    native.set_panic_handler()
    graph_scheduler_helper = EngineInitializer.setup_legacy_graph(native,
                                                                  self._global_options,
                                                                  self._build_config)
    return graph_scheduler_helper.new_session()

  def _get_target_roots(self, graph_helper, exclude_target_regexps, tags):
    return self._target_roots or TargetRootsCalculator.create(
      options=self._options,
      session=graph_helper.scheduler_session,
      build_root=self._root_dir,
      symbol_table=graph_helper.symbol_table,
      exclude_patterns=tuple(exclude_target_regexps),
      tags=tuple(tags)
    )

  def _determine_goals(self, requested_goals):
    """Check and populate the requested goals for a given run."""
    spec_parser = CmdLineSpecParser(self._root_dir)

    if self._address_mapper:
      for goal in requested_goals:
        if self._address_mapper.is_valid_single_address(spec_parser.parse_spec(goal)):
          logger.warning("Command-line argument '{0}' is ambiguous and was assumed to be "
                         "a goal. If this is incorrect, disambiguate it with ./{0}.".format(goal))

    goals = [Goal.by_name(goal) for goal in requested_goals]
    return goals

  def _roots_to_targets(self, target_roots):
    """Populate the BuildGraph and target list from a set of input TargetRoots."""
    with self._run_tracker.new_workunit(name='parse', labels=[WorkUnitLabel.SETUP]):

      def generate_targets():
        for address in self._build_graph.inject_roots_closure(target_roots, self._fail_fast):
          yield self._build_graph.get_target(address)

      return list(generate_targets())

  def _should_be_quiet(self, goals):
    if self._explain:
      return True

    if self._global_options.get_rank('quiet') > RankedValue.HARDCODED:
      return self._global_options.quiet

    return any(goal.has_task_of_type(QuietTaskMixin) for goal in goals)

  def _setup_context(self):
    with self._run_tracker.new_workunit(name='setup', labels=[WorkUnitLabel.SETUP]):
      graph_helper = self._get_graph_helper()
      target_roots = self._get_target_roots(
        graph_helper,
        self._global_options.exclude_target_regexp,
        self._global_options.tag
      )

      if self._global_options.v1:
        if not (isinstance(self._help_request, UnknownGoalHelp) and self._global_options.v2):
          self._handle_help(self._help_request)

        self._build_graph, self._address_mapper = graph_helper.create_build_graph(
          target_roots,
          self._root_dir
        )

      # If we're purely running in `--v2` mode, validate requested goals.
      if (self._global_options.v2 is True and
          self._global_options.v1 is False and
          (not self._is_daemon_run)):
        # TODO: self._requested_goals currently relies on existing v1 `Task` option scope
        # shadowing (i.e. the v1 scope must already exist) by way of the current handling
        # of `ArgSplitter` -> `Options.goals`.
        graph_helper.validate_goals(self._requested_goals)

      goals = self._determine_goals(self._requested_goals)
      is_quiet = self._should_be_quiet(goals)

      target_root_instances = self._roots_to_targets(
        target_roots
      ) if self._global_options.v1 else []

      # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
      self._run_tracker.run_info.add_scm_info()

      # Update the Reporting settings now that we have options and goal info.
      invalidation_report = self._reporting.update_reporting(self._global_options,
                                                             is_quiet,
                                                             self._run_tracker)

      context = Context(options=self._options,
                        run_tracker=self._run_tracker,
                        target_roots=target_root_instances,
                        v2_target_roots=target_roots,
                        requested_goals=self._requested_goals,
                        build_graph=self._build_graph,
                        build_file_parser=self._build_file_parser,
                        address_mapper=self._address_mapper,
                        invalidation_report=invalidation_report,
                        scheduler=graph_helper.scheduler_session,
                        graph_helper=graph_helper)

      return goals, context

  def setup(self):
    goals, context = self._setup_context()
    return GoalRunner(context=context,
                      goals=goals,
                      run_tracker=self._run_tracker,
                      kill_nailguns=self._kill_nailguns,
                      exiter=self._exiter,
                      is_daemon_run=self._is_daemon_run)


class GoalRunner(object):
  """Lists installed goals or else executes a named goal."""

  Factory = GoalRunnerFactory

  def __init__(self, context, goals, run_tracker, kill_nailguns, is_daemon_run, exiter=sys.exit):
    """
    :param Context context: The global, pre-initialized Context as created by GoalRunnerFactory.
    :param list[Goal] goals: The list of goals to act on.
    :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
    :param bool kill_nailguns: Whether or not to kill nailguns after the run.
    :param bool is_daemon_run: Whether or not this run was launched by the daemon.
    :param func exiter: A function that accepts an exit code value and exits (for tests, Optional).
    """
    self._context = context
    self._goals = goals
    self._run_tracker = run_tracker
    self._kill_nailguns = kill_nailguns
    self._is_daemon_run = is_daemon_run
    self._exiter = exiter

  def _validate_workdir(self, workdir):
    if not workdir.endswith('.pants.d'):
      self._context.log.error(
        'Pants working directory should end with \'.pants.d\', currently it is {}\n'
        .format(workdir)
      )
      return 1

  def _validate_goals(self):
    unknown_goals = [goal.name for goal in self._goals if not goal.ordered_task_names()]
    if unknown_goals:
      self._context.log.error('Unknown goal(s): {}\n'.format(' '.join(unknown_goals)))
      return 1

  def _execute_v1_tasks(self):
    should_kill_nailguns = self._kill_nailguns

    try:
      with self._context.executing():
        engine = RoundEngine()
        sorted_goal_infos = engine.sort_goals(self._context, self._goals)
        RunTracker.global_instance().set_sorted_goal_infos(sorted_goal_infos)
        result = engine.execute(self._context, self._goals)

        if self._context.invalidation_report:
          self._context.invalidation_report.report()

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

  def _execute_v2_rules(self):
    self._context.graph_helper.run_console_rules(
      self._context.requested_goals,
      self._context.v2_target_roots
    )
    return 0

  def run(self):
    v1_results = v2_results = 0
    global_options = self._context.options.for_global_scope()
    self._validate_workdir(global_options.pants_workdir)

    # N.B. For daemon runs, console rules execute pre-fork.
    if (not self._is_daemon_run) and global_options.v2:
      v2_results = self._execute_v2_rules()

    if global_options.v1:
      self._validate_goals()
      v1_results = self._execute_v1_tasks()

    return max((v1_results, v2_results))
