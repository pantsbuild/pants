# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
from typing import List

from pants.base.specs import AddressSpecs, FilesystemSpecs, SingleAddress, Specs
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_parser import BuildFileParser
from pants.engine.addressable import Addresses
from pants.engine.legacy.graph import LegacyBuildGraph
from pants.engine.round_engine import RoundEngine
from pants.engine.selectors import Params
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.init.engine_initializer import LegacyGraphSession
from pants.java.nailgun_executor import NailgunProcessGroup
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.ranked_value import Rank
from pants.reporting.reporting import Reporting
from pants.task.task import QuietTaskMixin

logger = logging.getLogger(__name__)


class GoalRunnerFactory:
    def __init__(
        self,
        root_dir: str,
        options_bootstrapper: OptionsBootstrapper,
        options: Options,
        build_config: BuildConfiguration,
        run_tracker: RunTracker,
        reporting: Reporting,
        graph_session: LegacyGraphSession,
        specs: Specs,
        exiter=sys.exit,
    ) -> None:
        """
        :param root_dir: The root directory of the pants workspace (aka the "build root").
        :param options: The global, pre-initialized Options instance.
        :param build_config: A pre-initialized BuildConfiguration instance.
        :param run_tracker: The global, pre-initialized/running RunTracker instance.
        :param reporting: The global, pre-initialized Reporting instance.
        :param graph_session: The graph session for this run.
        :param specs: The specs for this run, i.e. either the address or filesystem specs.
        :param func exiter: A function that accepts an exit code value and exits. (for tests, Optional)
        """
        self._root_dir = root_dir
        self._options_bootstrapper = options_bootstrapper
        self._options = options
        self._build_config = build_config
        self._run_tracker = run_tracker
        self._reporting = reporting
        self._graph_session = graph_session
        self._specs = specs
        self._exiter = exiter

        self._global_options = options.for_global_scope()
        self._fail_fast = self._global_options.fail_fast
        self._explain = self._global_options.explain
        self._kill_nailguns = self._global_options.kill_nailguns

        # V1 tasks do not understand FilesystemSpecs, so we eagerly convert them into AddressSpecs.
        if self._specs.filesystem_specs.dependencies:
            (owned_addresses,) = self._graph_session.scheduler_session.product_request(
                Addresses, [Params(self._specs.filesystem_specs, self._options_bootstrapper)]
            )
            updated_address_specs = AddressSpecs(
                dependencies=tuple(
                    SingleAddress(a.spec_path, a.target_name) for a in owned_addresses
                ),
                tags=self._specs.address_specs.matcher.tags,
                exclude_patterns=self._specs.address_specs.matcher.exclude_patterns,
            )
            self._specs = Specs(
                address_specs=updated_address_specs, filesystem_specs=FilesystemSpecs([]),
            )

    def _determine_v1_goals(self, options: Options) -> List[Goal]:
        """Check and populate the requested goals for a given run."""
        v1_goals, ambiguous_goals, _ = options.goals_by_version
        return [Goal.by_name(goal) for goal in v1_goals + ambiguous_goals]

    def _address_specs_to_targets(self, build_graph: LegacyBuildGraph, address_specs: AddressSpecs):
        """Populate the BuildGraph and target list from a set of input TargetRoots."""
        with self._run_tracker.new_workunit(name="parse", labels=[WorkUnitLabel.SETUP]):
            return [
                build_graph.get_target(address)
                for address in build_graph.inject_roots_closure(address_specs, self._fail_fast)
            ]

    def _should_be_quiet(self, goals):
        if self._explain:
            return True

        if self._global_options.get_rank("quiet") > Rank.HARDCODED:
            return self._global_options.quiet

        return any(goal.has_task_of_type(QuietTaskMixin) for goal in goals)

    def _setup_context(self):
        with self._run_tracker.new_workunit(name="setup", labels=[WorkUnitLabel.SETUP]):
            build_file_parser = BuildFileParser(self._build_config, self._root_dir)
            build_graph, address_mapper = self._graph_session.create_build_graph(
                self._specs, self._root_dir
            )

            goals = self._determine_v1_goals(self._options)
            is_quiet = self._should_be_quiet(goals)

            target_root_instances = self._address_specs_to_targets(
                build_graph, self._specs.address_specs,
            )

            # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
            self._run_tracker.run_info.add_scm_info()

            # Update the Reporting settings now that we have options and goal info.
            invalidation_report = self._reporting.update_reporting(
                self._global_options, is_quiet, self._run_tracker
            )

            context = Context(
                options=self._options,
                run_tracker=self._run_tracker,
                target_roots=target_root_instances,
                requested_goals=self._options.goals,
                build_graph=build_graph,
                build_file_parser=build_file_parser,
                build_configuration=self._build_config,
                address_mapper=address_mapper,
                invalidation_report=invalidation_report,
                scheduler=self._graph_session.scheduler_session,
            )

            return goals, context

    def create(self) -> "GoalRunner":
        goals, context = self._setup_context()
        return GoalRunner(
            context=context,
            goals=goals,
            run_tracker=self._run_tracker,
            kill_nailguns=self._kill_nailguns,
        )


class GoalRunner:
    """Lists installed goals or else executes a named goal.

    NB: GoalRunner represents a v1-only codepath. v2 goals are registered via `@goal_rule` and
    the `pants.engine.goal.Goal` class.
    """

    Factory = GoalRunnerFactory

    def __init__(self, context, goals, run_tracker, kill_nailguns):
        """
        :param Context context: The global, pre-initialized Context as created by GoalRunnerFactory.
        :param list[Goal] goals: The list of goals to act on.
        :param Runtracker run_tracker: The global, pre-initialized/running RunTracker instance.
        :param bool kill_nailguns: Whether or not to kill nailguns after the run.
        """
        self._context = context
        self._goals = goals
        self._run_tracker = run_tracker
        self._kill_nailguns = kill_nailguns

    def _is_valid_workdir(self, workdir):
        if workdir.endswith(".pants.d"):
            return True

        self._context.log.error(
            "Pants working directory should end with '.pants.d', currently it is {}\n".format(
                workdir
            )
        )
        return False

    def _execute_engine(self) -> int:
        engine = RoundEngine()
        sorted_goal_infos = engine.sort_goals(self._context, self._goals)
        RunTracker.global_instance().set_sorted_goal_infos(sorted_goal_infos)
        result = engine.execute(self._context, self._goals)

        if self._context.invalidation_report:
            self._context.invalidation_report.report()

        return result

    def _run_goals(self) -> int:
        should_kill_nailguns = self._kill_nailguns

        try:
            with self._context.executing():
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

    def run(self) -> int:
        global_options = self._context.options.for_global_scope()

        if not self._is_valid_workdir(global_options.pants_workdir):
            return 1

        return self._run_goals()
