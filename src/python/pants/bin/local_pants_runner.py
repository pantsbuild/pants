# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.base.workunit import WorkUnit
from pants.build_graph.build_configuration import BuildConfiguration
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.internals.native import Native
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.session import SessionValues
from pants.engine.unions import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.help.flag_error_help_printer import FlagErrorHelpPrinter
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import EngineInitializer, GraphScheduler, GraphSession
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.init.specs_calculator import calculate_specs
from pants.option.errors import UnknownFlagsError
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.subsystem import Subsystem
from pants.reporting.streaming_workunit_handler import StreamingWorkunitHandler
from pants.util.contextutil import maybe_profiled

logger = logging.getLogger(__name__)


@dataclass
class LocalPantsRunner:
    """Handles a single pants invocation running in the process-local context.

    build_root: The build root for this run.
    options: The parsed options for this run.
    build_config: The parsed build configuration for this run.
    specs: The specs for this run, i.e. either the address or filesystem specs.
    graph_session: A LegacyGraphSession instance for graph reuse.
    profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
    """

    build_root: str
    options: Options
    build_config: BuildConfiguration
    specs: Specs
    graph_session: GraphSession
    union_membership: UnionMembership
    profile_path: Optional[str]
    _run_tracker: RunTracker

    @classmethod
    def parse_options(
        cls,
        options_bootstrapper: OptionsBootstrapper,
    ) -> Tuple[Options, BuildConfiguration]:
        build_config = BuildConfigInitializer.get(options_bootstrapper)
        try:
            options = OptionsInitializer.create(options_bootstrapper, build_config)
        except UnknownFlagsError as err:
            cls._handle_unknown_flags(err, options_bootstrapper)
            raise
        return options, build_config

    @classmethod
    def _init_graph_session(
        cls,
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        options: Options,
        scheduler: Optional[GraphScheduler] = None,
    ) -> GraphSession:
        native = Native()
        native.set_panic_handler()
        graph_scheduler_helper = scheduler or EngineInitializer.setup_graph(
            options_bootstrapper, build_config
        )

        try:
            global_scope = options.for_global_scope()
        except UnknownFlagsError as err:
            cls._handle_unknown_flags(err, options_bootstrapper)
            raise
        dynamic_ui = global_scope.dynamic_ui if global_scope.v2 else False
        use_colors = global_scope.get("colors", True)

        stream_workunits = len(options.for_global_scope().streaming_workunits_handlers) != 0
        return graph_scheduler_helper.new_session(
            RunTracker.global_instance().run_id,
            dynamic_ui=dynamic_ui,
            use_colors=use_colors,
            should_report_workunits=stream_workunits,
            session_values=SessionValues(
                {
                    OptionsBootstrapper: options_bootstrapper,
                    PantsEnvironment: PantsEnvironment(os.environ),
                }
            ),
        )

    @staticmethod
    def _handle_unknown_flags(err: UnknownFlagsError, options_bootstrapper: OptionsBootstrapper):
        build_config = BuildConfigInitializer.get(options_bootstrapper)
        # We need an options instance in order to get "did you mean" suggestions, but we know
        # there are bad flags in the args, so we generate options with no flags.
        no_arg_bootstrapper = replace(options_bootstrapper, args=("dummy_first_arg",))
        options = OptionsInitializer.create(no_arg_bootstrapper, build_config)
        FlagErrorHelpPrinter(options).handle_unknown_flags(err)

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        options_bootstrapper: OptionsBootstrapper,
        scheduler: Optional[GraphScheduler] = None,
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
        options, build_config = cls.parse_options(options_bootstrapper)

        union_membership = UnionMembership.from_rules(build_config.union_rules)

        # If we're running with the daemon, we'll be handed a warmed Scheduler, which we use
        # to initialize a session here.
        graph_session = cls._init_graph_session(
            options_bootstrapper, build_config, options, scheduler
        )

        # Option values are usually computed lazily on demand,
        # but command line options are eagerly computed for validation.
        for scope in options.scope_to_flags.keys():
            try:
                options.for_scope(scope)
            except UnknownFlagsError as err:
                cls._handle_unknown_flags(err, options_bootstrapper)
                raise

        # Verify configs.
        if global_bootstrap_options.verify_config:
            options.verify_configs(options_bootstrapper.config)

        specs = calculate_specs(
            options_bootstrapper=options_bootstrapper,
            options=options,
            build_root=build_root,
            session=graph_session.scheduler_session,
        )

        profile_path = env.get("PANTS_PROFILE")

        return cls(
            build_root=build_root,
            options=options,
            build_config=build_config,
            specs=specs,
            graph_session=graph_session,
            union_membership=union_membership,
            profile_path=profile_path,
            _run_tracker=RunTracker.global_instance(),
        )

    def _set_start_time(self, start_time: float) -> None:
        self._run_tracker.start(self.options, run_start_time=start_time)

        spec_parser = SpecsParser(get_buildroot())
        specs = [str(spec_parser.parse_spec(spec)) for spec in self.options.specs]
        # Note: This will not include values from `--changed-*` flags.
        self._run_tracker.run_info.add_info("specs_from_command_line", specs, stringify=False)

    def _run_v2(self) -> ExitCode:
        goals = self.options.goals
        self._run_tracker.set_v2_goal_rule_names(tuple(goals))
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
            union_membership=self.union_membership,
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

    def _finish_run(self, code: ExitCode) -> ExitCode:
        """Checks that the RunTracker is in good shape to exit, and then returns its exit code.

        TODO: The RunTracker's exit code will likely not be relevant in v2: the exit codes of
        individual `@goal_rule`s are everything in that case.
        """

        run_tracker_result = PANTS_SUCCEEDED_EXIT_CODE
        scheduler_session = self.graph_session.scheduler_session

        try:
            metrics = scheduler_session.metrics()
            self._run_tracker.pantsd_stats.set_scheduler_metrics(metrics)
            outcome = WorkUnit.SUCCESS if code == PANTS_SUCCEEDED_EXIT_CODE else WorkUnit.FAILURE
            self._run_tracker.set_root_outcome(outcome)
            run_tracker_result = self._run_tracker.end()
        except ValueError as e:
            # If we have been interrupted by a signal, calling .end() sometimes writes to a closed
            # file, so we just log that fact here and keep going.
            ExceptionSink.log_exception(exc=e)

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
                all_help_info = HelpInfoExtracter.get_all_help_info(
                    self.options,
                    self.union_membership,
                    self.graph_session.goal_consumed_subsystem_scopes,
                )
                help_printer = HelpPrinter(
                    bin_name=global_options.pants_bin_name,
                    help_request=self.options.help_request,
                    all_help_info=all_help_info,
                    color=global_options.colors,
                )
                return help_printer.print_help()

            with streaming_reporter.session():
                engine_result = PANTS_FAILED_EXIT_CODE
                try:
                    engine_result = self._run_v2()
                except Exception as e:
                    ExceptionSink.log_exception(e)
                run_tracker_result = self._finish_run(engine_result)
            return self._merge_exit_codes(engine_result, run_tracker_result)
