# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

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
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.goal.run_tracker import RunTracker
from pants.init.engine_initializer import EngineInitializer, GraphScheduler, GraphSession
from pants.init.logging import stdio_destination_use_color
from pants.init.options_initializer import OptionsInitializer
from pants.init.specs_calculator import calculate_specs
from pants.option.global_options import DynamicRemoteOptions, DynamicUIRenderer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import maybe_profiled
from pants.util.logging import LogLevel

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
    profile_path: str | None

    @classmethod
    def _init_graph_session(
        cls,
        options_initializer: OptionsInitializer,
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        env: CompleteEnvironment,
        run_id: str,
        options: Options,
        scheduler: GraphScheduler | None = None,
        cancellation_latch: PySessionCancellationLatch | None = None,
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
            ui_use_prodash=global_options.dynamic_ui_renderer
            == DynamicUIRenderer.experimental_prodash,
            use_colors=global_options.get("colors", True),
            max_workunit_level=max(
                global_options.streaming_workunits_level,
                global_options.level,
                *(
                    LogLevel[level.upper()]
                    for level in global_options.log_levels_by_target.values()
                ),
            ),
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
        options_initializer: OptionsInitializer | None = None,
        scheduler: GraphScheduler | None = None,
        cancellation_latch: PySessionCancellationLatch | None = None,
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
        stdio_destination_use_color(options.for_global_scope().colors)

        run_tracker = RunTracker(options_bootstrapper.args, options)
        union_membership = UnionMembership.from_rules(build_config.union_rules)

        # Option values are usually computed lazily on demand, but command line options are
        # eagerly computed for validation.
        with options_initializer.handle_unknown_flags(options_bootstrapper, env, raise_=True):
            for scope, values in options.scope_to_flags.items():
                if values:
                    # Only compute values if there were any command line options presented.
                    options.for_scope(scope)

        # Verify configs.
        global_bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        if global_bootstrap_options.verify_config:
            options.verify_configs(options_bootstrapper.config)

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

        specs = calculate_specs(
            options_bootstrapper=options_bootstrapper,
            options=options,
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

    def _perform_run(self, goals: tuple[str, ...]) -> ExitCode:
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
                logger.error(e)
            iterations -= 1

        return exit_code

    def _perform_run_body(self, goals: tuple[str, ...], poll: bool) -> ExitCode:
        return self.graph_session.run_goal_rules(
            union_membership=self.union_membership,
            goals=goals,
            specs=self.specs,
            poll=poll,
            poll_delay=(0.1 if poll else None),
        )

    def _finish_run(self, code: ExitCode) -> None:
        """Cleans up the run tracker."""

    def _get_workunits_callbacks(self) -> tuple[WorkunitsCallback, ...]:
        # Load WorkunitsCallbacks by requesting WorkunitsCallbackFactories, and then constructing
        # a per-run instance of each WorkunitsCallback.
        (workunits_callback_factories,) = self.graph_session.scheduler_session.product_request(
            WorkunitsCallbackFactories, [self.union_membership]
        )
        return tuple(filter(bool, (wcf.callback_factory() for wcf in workunits_callback_factories)))

    def _run_builtin_goal(self, builtin_goal: str) -> ExitCode:
        scope_info = self.options.known_scope_to_info[builtin_goal]
        assert scope_info.subsystem_cls
        scoped_options = self.options.for_scope(builtin_goal)
        goal = scope_info.subsystem_cls(scoped_options)
        assert isinstance(goal, BuiltinGoal)
        return goal.run(
            build_config=self.build_config,
            graph_session=self.graph_session,
            options=self.options,
            specs=self.specs,
            union_membership=self.union_membership,
        )

    def _run_inner(self) -> ExitCode:
        if self.options.builtin_goal:
            return self._run_builtin_goal(self.options.builtin_goal)

        goals = tuple(self.options.goals)
        if not goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        try:
            return self._perform_run(goals)
        except Exception as e:
            logger.error(e)
            return PANTS_FAILED_EXIT_CODE
        except KeyboardInterrupt:
            print("Interrupted by user.\n", file=sys.stderr)
            return PANTS_FAILED_EXIT_CODE

    def run(self, start_time: float) -> ExitCode:
        with maybe_profiled(self.profile_path):
            spec_parser = SpecsParser()
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
                allow_async_completion=(
                    global_options.pantsd and global_options.streaming_workunits_complete_async
                ),
                max_workunit_verbosity=global_options.streaming_workunits_level,
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
