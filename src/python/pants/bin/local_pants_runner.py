# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.deprecated import resolve_conflicting_options
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.base.workunit import WorkUnit
from pants.bin.goal_runner import GoalRunner
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.internals.native import Native
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.unions import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import (
    EngineInitializer,
    LegacyGraphScheduler,
    LegacyGraphSession,
)
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.init.repro import Repro, Reproducer
from pants.init.specs_calculator import SpecsCalculator
from pants.option.arg_splitter import UnknownGoalHelp
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE
from pants.reporting.reporting import Reporting
from pants.reporting.streaming_workunit_handler import StreamingWorkunitHandler
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import maybe_profiled

logger = logging.getLogger(__name__)


@dataclass
class LocalPantsRunner:
    """Handles a single pants invocation running in the process-local context.

    build_root: The build root for this run.
    options: The parsed options for this run.
    options_bootstrapper: The OptionsBootstrapper instance to use.
    build_config: The parsed build configuration for this run.
    specs: The specs for this run, i.e. either the address or filesystem specs.
    graph_session: A LegacyGraphSession instance for graph reuse.
    profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
    """

    build_root: str
    options: Options
    options_bootstrapper: OptionsBootstrapper
    build_config: BuildConfiguration
    specs: Specs
    graph_session: LegacyGraphSession
    union_membership: UnionMembership
    profile_path: Optional[str]
    _run_tracker: RunTracker
    _reporting: Optional[Reporting] = None
    _repro: Optional[Repro] = None

    @staticmethod
    def parse_options(
        options_bootstrapper: OptionsBootstrapper,
    ) -> Tuple[Options, BuildConfiguration]:
        build_config = BuildConfigInitializer.get(options_bootstrapper)
        options = OptionsInitializer.create(options_bootstrapper, build_config)
        return options, build_config

    @staticmethod
    def _init_graph_session(
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        options: Options,
        scheduler: Optional[LegacyGraphScheduler] = None,
    ) -> LegacyGraphSession:
        native = Native()
        native.set_panic_handler()
        graph_scheduler_helper = scheduler or EngineInitializer.setup_legacy_graph(
            options_bootstrapper, build_config
        )

        global_scope = options.for_global_scope()

        if global_scope.v2:
            dynamic_ui = resolve_conflicting_options(
                old_option="v2_ui",
                new_option="dynamic_ui",
                old_scope=GLOBAL_SCOPE,
                new_scope=GLOBAL_SCOPE,
                old_container=global_scope,
                new_container=global_scope,
            )
        else:
            dynamic_ui = False
        use_colors = global_scope.get("colors", True)

        zipkin_trace_v2 = options.for_scope("reporting").zipkin_trace_v2
        # TODO(#8658) This should_report_workunits flag must be set to True for
        # StreamingWorkunitHandler to receive WorkUnits. It should eventually
        # be merged with the zipkin_trace_v2 flag, since they both involve most
        # of the same engine functionality, but for now is separate to avoid
        # breaking functionality associated with zipkin tracing while iterating on streaming workunit reporting.
        stream_workunits = len(options.for_global_scope().streaming_workunits_handlers) != 0
        return graph_scheduler_helper.new_session(
            zipkin_trace_v2,
            RunTracker.global_instance().run_id,
            dynamic_ui=dynamic_ui,
            use_colors=use_colors,
            should_report_workunits=stream_workunits,
        )

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        options_bootstrapper: OptionsBootstrapper,
        scheduler: Optional[LegacyGraphScheduler] = None,
    ) -> "LocalPantsRunner":
        """Creates a new LocalPantsRunner instance by parsing options.

        By the time this method runs, logging will already have been initialized in either
        PantsRunner or DaemonPantsRunner.

        :param env: The environment (e.g. os.environ) for this run.
        :param options_bootstrapper: The OptionsBootstrapper instance to reuse.
        :param scheduler: If being called from the daemon, a warmed scheduler to use.
        """
        build_root = get_buildroot()
        global_bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        options, build_config = LocalPantsRunner.parse_options(options_bootstrapper)

        # Option values are usually computed lazily on demand,
        # but command line options are eagerly computed for validation.
        for scope in options.scope_to_flags.keys():
            options.for_scope(scope)

        # Verify configs.
        if global_bootstrap_options.verify_config:
            options.verify_configs(options_bootstrapper.config)

        union_membership = UnionMembership(build_config.union_rules())

        # If we're running with the daemon, we'll be handed a warmed Scheduler, which we use
        # to initialize a session here.
        graph_session = cls._init_graph_session(
            options_bootstrapper, build_config, options, scheduler
        )

        global_options = options.for_global_scope()
        specs = SpecsCalculator.create(
            options=options,
            build_root=build_root,
            session=graph_session.scheduler_session,
            exclude_patterns=tuple(global_options.exclude_target_regexp),
            tags=tuple(global_options.tag),
        )

        profile_path = env.get("PANTS_PROFILE")

        return cls(
            build_root=build_root,
            options=options,
            options_bootstrapper=options_bootstrapper,
            build_config=build_config,
            specs=specs,
            graph_session=graph_session,
            union_membership=union_membership,
            profile_path=profile_path,
            _run_tracker=RunTracker.global_instance(),
        )

    def _set_start_time(self, start_time: float) -> None:
        # Propagates parent_build_id to pants runs that may be called from this pants run.
        os.environ["PANTS_PARENT_BUILD_ID"] = self._run_tracker.run_id

        self._reporting = Reporting.global_instance()
        self._reporting.initialize(self._run_tracker, self.options, start_time=start_time)

        spec_parser = CmdLineSpecParser(get_buildroot())
        specs = [spec_parser.parse_spec(spec).to_spec_string() for spec in self.options.specs]
        # Note: This will not include values from `--changed-*` flags.
        self._run_tracker.run_info.add_info("specs_from_command_line", specs, stringify=False)

        # Capture a repro of the 'before' state for this build, if needed.
        self._repro = Reproducer.global_instance().create_repro()
        if self._repro:
            self._repro.capture(self._run_tracker.run_info.get_as_dict())

    def _maybe_run_v1(self, v1: bool) -> ExitCode:
        v1_goals, ambiguous_goals, _ = self.options.goals_by_version
        if not v1:
            if v1_goals:
                HelpPrinter(
                    options=self.options,
                    help_request=UnknownGoalHelp(list(v1_goals)),
                    union_membership=self.union_membership,
                ).print_help()
                return PANTS_FAILED_EXIT_CODE
            return PANTS_SUCCEEDED_EXIT_CODE

        if not v1_goals and not ambiguous_goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        # Setup and run GoalRunner.
        return (
            GoalRunner.Factory(
                self.build_root,
                self.options_bootstrapper,
                self.options,
                self.build_config,
                self._run_tracker,
                self._reporting,  # type: ignore
                self.graph_session,
                self.specs,
            )
            .create()
            .run()
        )

    def _maybe_run_v2(self, v2: bool) -> ExitCode:
        _, ambiguous_goals, v2_goals = self.options.goals_by_version
        goals = v2_goals + (ambiguous_goals if v2 else tuple())
        if self._run_tracker:
            self._run_tracker.set_v2_goal_rule_names(goals)
        if not goals:
            return PANTS_SUCCEEDED_EXIT_CODE
        global_options = self.options.for_global_scope()
        if not global_options.get("loop", False):
            return self._maybe_run_v2_body(goals, poll=False)

        iterations = global_options.loop_max
        exit_code = PANTS_SUCCEEDED_EXIT_CODE
        while iterations:
            # NB: We generate a new "run id" per iteration of the loop in order to allow us to
            # observe fresh values for Goals. See notes in `scheduler.rs`.
            self.graph_session.scheduler_session.new_run_id()
            try:
                exit_code = self._maybe_run_v2_body(goals, poll=True)
            except ExecutionError as e:
                logger.warning(e)
            iterations -= 1

        return exit_code

    def _maybe_run_v2_body(self, goals, poll: bool) -> ExitCode:
        return self.graph_session.run_goal_rules(
            options_bootstrapper=self.options_bootstrapper,
            union_membership=self.union_membership,
            options=self.options,
            goals=goals,
            specs=self.specs,
            poll=poll,
            poll_delay=(0.1 if poll else None),
        )

    @staticmethod
    def _merge_exit_codes(code: ExitCode, *codes: ExitCode) -> ExitCode:
        """Returns the exit code with higher abs value in case of negative values."""
        max_code = code
        for code in codes:
            if abs(max_code) < abs(code):
                max_code = code
        return max_code

    def _update_stats(self):
        scheduler_session = self.graph_session.scheduler_session
        metrics = scheduler_session.metrics()
        self._run_tracker.pantsd_stats.set_scheduler_metrics(metrics)
        engine_workunits = scheduler_session.engine_workunits(metrics)
        if engine_workunits:
            self._run_tracker.report.bulk_record_workunits(engine_workunits)

    def _finish_run(self, code: ExitCode) -> ExitCode:
        """Checks that the RunTracker is in good shape to exit, and then returns its exit code.

        TODO: The RunTracker's exit code will likely not be relevant in v2: the exit codes of
        individual `@goal_rule`s are everything in that case.
        """

        run_tracker_result = PANTS_SUCCEEDED_EXIT_CODE

        # These strings are prepended to the existing exit message when calling the superclass .exit().
        additional_messages = []
        try:
            self._update_stats()

            if code == PANTS_SUCCEEDED_EXIT_CODE:
                outcome = WorkUnit.SUCCESS
            elif code == PANTS_FAILED_EXIT_CODE:
                outcome = WorkUnit.FAILURE
            else:
                run_tracker_msg = (
                    "unrecognized exit code {} provided to {}.exit() -- "
                    "interpreting as a failure in the run tracker".format(code, type(self).__name__)
                )
                # Log the unrecognized exit code to the fatal exception log.
                ExceptionSink.log_exception(exc=Exception(run_tracker_msg))
                # Ensure the unrecognized exit code message is also logged to the terminal.
                additional_messages.append(run_tracker_msg)
                outcome = WorkUnit.FAILURE

            self._run_tracker.set_root_outcome(outcome)
            run_tracker_result = self._run_tracker.end()
        except ValueError as e:
            # If we have been interrupted by a signal, calling .end() sometimes writes to a closed file,
            # so we just log that fact here and keep going.
            ExceptionSink.log_exception(exc=e)
        finally:
            if self._repro:
                # TODO: Have Repro capture the 'after' state (as a diff) as well? (in reference to the below
                # 'before' state comment)
                # NB: this writes to the logger, which is expected to still be alive if we are exiting from
                # a signal.
                self._repro.log_location_of_repro_file()

        if additional_messages:
            # NB: We do not log to the exceptions log in this case, because we expect that these are
            # higher level unstructured errors: structured versions will already have been written at
            # various places.
            logger.error("\n".join(additional_messages))

        return run_tracker_result

    def run(self, start_time: float) -> ExitCode:
        self._set_start_time(start_time)

        with maybe_profiled(self.profile_path):
            global_options = self.options.for_global_scope()
            streaming_handlers = global_options.streaming_workunits_handlers
            report_interval = global_options.streaming_workunits_report_interval
            callbacks = Subsystem.get_streaming_workunit_callbacks(streaming_handlers)
            streaming_reporter = StreamingWorkunitHandler(
                self.graph_session.scheduler_session,
                callbacks=callbacks,
                report_interval_seconds=report_interval,
            )

            if self.options.help_request:
                help_printer = HelpPrinter(
                    options=self.options, union_membership=self.union_membership
                )
                return help_printer.print_help()

            v1 = global_options.v1
            v2 = global_options.v2
            with streaming_reporter.session():
                engine_result, goal_runner_result = PANTS_FAILED_EXIT_CODE, PANTS_FAILED_EXIT_CODE
                try:
                    engine_result = self._maybe_run_v2(v2)
                    goal_runner_result = self._maybe_run_v1(v1)
                except Exception as e:
                    ExceptionSink.log_exception(e)
                run_tracker_result = self._finish_run(
                    self._merge_exit_codes(engine_result, goal_runner_result)
                )
            return self._merge_exit_codes(engine_result, goal_runner_result, run_tracker_result)
