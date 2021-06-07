# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import PySessionCancellationLatch
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.session import SessionValues
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitHandler,
    WorkunitsCallback,
    WorkunitsCallbackFactories,
)
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import EngineInitializer, GraphScheduler, GraphSession
from pants.init.options_initializer import OptionsInitializer
from pants.init.specs_calculator import calculate_specs
from pants.option.arg_splitter import HelpRequest
from pants.option.global_options import DynamicRemoteOptions
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import maybe_profiled

logger = logging.getLogger(__name__)


@dataclass
class LocalPantsRunner:
    """Handles a single pants invocation running in the process-local context.

    options: The parsed options for this run.
    build_config: The parsed build configuration for this run.
    run_tracker: A tracker for metrics for the run.
    specs: The specs for this run, i.e. either the address or filesystem specs.
    graph_session: A LegacyGraphSession instance for graph reuse.
    profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
    """

    options: Options
    options_bootstrapper: OptionsBootstrapper
    build_config: BuildConfiguration
    run_tracker: RunTracker
    specs: Specs
    graph_session: GraphSession
    union_membership: UnionMembership
    profile_path: Optional[str]

    @classmethod
    def _init_graph_session(
        cls,
        options_initializer: OptionsInitializer,
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        env: CompleteEnvironment,
        run_id: str,
        options: Options,
        scheduler: Optional[GraphScheduler] = None,
        cancellation_latch: Optional[PySessionCancellationLatch] = None,
    ) -> GraphSession:
        native_engine.maybe_set_panic_handler()
        if scheduler is None:
            dynamic_remote_options, _ = DynamicRemoteOptions.from_options(options, env)
            bootstrap_options = options.bootstrap_option_values()
            assert bootstrap_options is not None
            scheduler = EngineInitializer.setup_graph(
                bootstrap_options, build_config, dynamic_remote_options
            )
        with options_initializer.handle_unknown_flags(options_bootstrapper, env, raise_=True):
            global_options = options.for_global_scope()
        return scheduler.new_session(
            run_id,
            dynamic_ui=global_options.dynamic_ui,
            use_colors=global_options.get("colors", True),
            session_values=SessionValues(
                {
                    OptionsBootstrapper: options_bootstrapper,
                    CompleteEnvironment: env,
                }
            ),
            cancellation_latch=cancellation_latch,
        )

    @classmethod
    def create(
        cls,
        env: CompleteEnvironment,
        options_bootstrapper: OptionsBootstrapper,
        options_initializer: Optional[OptionsInitializer] = None,
        scheduler: Optional[GraphScheduler] = None,
        cancellation_latch: Optional[PySessionCancellationLatch] = None,
    ) -> LocalPantsRunner:
        """Creates a new LocalPantsRunner instance by parsing options.

        By the time this method runs, logging will already have been initialized in either
        PantsRunner or DaemonPantsRunner.

        :param env: The environment for this run.
        :param options_bootstrapper: The OptionsBootstrapper instance to reuse.
        :param scheduler: If being called from the daemon, a warmed scheduler to use.
        """
        options_initializer = options_initializer or OptionsInitializer(options_bootstrapper)
        build_config, options = options_initializer.build_config_and_options(
            options_bootstrapper, env, raise_=True
        )

        run_tracker = RunTracker(options_bootstrapper.args, options)
        union_membership = UnionMembership.from_rules(build_config.union_rules)

        # If we're running with the daemon, we'll be handed a warmed Scheduler, which we use
        # to initialize a session here.
        graph_session = cls._init_graph_session(
            options_initializer,
            options_bootstrapper,
            build_config,
            env,
            run_tracker.run_id,
            options,
            scheduler,
            cancellation_latch,
        )

        # Option values are usually computed lazily on demand, but command line options are
        # eagerly computed for validation.
        with options_initializer.handle_unknown_flags(options_bootstrapper, env, raise_=True):
            for scope in options.scope_to_flags.keys():
                options.for_scope(scope)

        # Verify configs.
        global_bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        if global_bootstrap_options.verify_config:
            options.verify_configs(options_bootstrapper.config)

        specs = calculate_specs(
            options_bootstrapper=options_bootstrapper,
            options=options,
            build_root=get_buildroot(),
            session=graph_session.scheduler_session,
        )

        profile_path = env.get("PANTS_PROFILE")

        return cls(
            options=options,
            options_bootstrapper=options_bootstrapper,
            build_config=build_config,
            run_tracker=run_tracker,
            specs=specs,
            graph_session=graph_session,
            union_membership=union_membership,
            profile_path=profile_path,
        )

    def _perform_run(self, goals: Tuple[str, ...]) -> ExitCode:
        global_options = self.options.for_global_scope()
        if not global_options.get("loop", False):
            return self._perform_run_body(goals, poll=False)

        iterations = global_options.loop_max
        exit_code = PANTS_SUCCEEDED_EXIT_CODE
        while iterations:
            # NB: We generate a new "run id" per iteration of the loop in order to allow us to
            # observe fresh values for Goals. See notes in `scheduler.rs`.
            self.graph_session.scheduler_session.new_run_id()
            try:
                exit_code = self._perform_run_body(goals, poll=True)
            except ExecutionError as e:
                logger.warning(e)
            iterations -= 1

        return exit_code

    def _perform_run_body(self, goals: Tuple[str, ...], poll: bool) -> ExitCode:
        return self.graph_session.run_goal_rules(
            union_membership=self.union_membership,
            goals=goals,
            specs=self.specs,
            poll=poll,
            poll_delay=(0.1 if poll else None),
        )

    def _finish_run(self, code: ExitCode) -> None:
        """Cleans up the run tracker."""

    def _print_help(self, request: HelpRequest) -> ExitCode:
        global_options = self.options.for_global_scope()

        all_help_info = HelpInfoExtracter.get_all_help_info(
            self.options,
            self.union_membership,
            self.graph_session.goal_consumed_subsystem_scopes,
            RegisteredTargetTypes.create(self.build_config.target_types),
        )
        help_printer = HelpPrinter(
            bin_name=global_options.pants_bin_name,
            help_request=request,
            all_help_info=all_help_info,
            color=global_options.colors,
        )
        return help_printer.print_help()

    def _get_workunits_callbacks(self) -> Tuple[WorkunitsCallback, ...]:
        # Load WorkunitsCallbacks by requesting WorkunitsCallbackFactories, and then constructing
        # a per-run instance of each WorkunitsCallback.
        (workunits_callback_factories,) = self.graph_session.scheduler_session.product_request(
            WorkunitsCallbackFactories, [self.union_membership]
        )
        return tuple(wcf.callback_factory() for wcf in workunits_callback_factories)

    def _run_inner(self) -> ExitCode:
        goals = tuple(self.options.goals)
        if self.options.help_request:
            return self._print_help(self.options.help_request)
        if not goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        try:
            return self._perform_run(goals)
        except Exception as e:
            ExceptionSink.log_exception(e)
            return PANTS_FAILED_EXIT_CODE
        except KeyboardInterrupt:
            print("Interrupted by user.\n", file=sys.stderr)
            return PANTS_FAILED_EXIT_CODE

    def run(self, start_time: float) -> ExitCode:
        with maybe_profiled(self.profile_path):
            spec_parser = SpecsParser(get_buildroot())
            specs = [str(spec_parser.parse_spec(spec)) for spec in self.options.specs]
            self.run_tracker.start(run_start_time=start_time, specs=specs)
            global_options = self.options.for_global_scope()

            streaming_reporter = StreamingWorkunitHandler(
                self.graph_session.scheduler_session,
                run_tracker=self.run_tracker,
                specs=self.specs,
                options_bootstrapper=self.options_bootstrapper,
                callbacks=self._get_workunits_callbacks(),
                report_interval_seconds=global_options.streaming_workunits_report_interval,
                pantsd=global_options.pantsd,
            )
            with streaming_reporter:
                engine_result = PANTS_FAILED_EXIT_CODE
                try:
                    engine_result = self._run_inner()
                finally:
                    metrics = self.graph_session.scheduler_session.metrics()
                    self.run_tracker.set_pantsd_scheduler_metrics(metrics)
                    self.run_tracker.end_run(engine_result)

                return engine_result
