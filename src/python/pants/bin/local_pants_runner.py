# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, Exiter
from pants.base.specs import Specs
from pants.base.workunit import WorkUnit
from pants.bin.goal_runner import GoalRunner
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.native import Native
from pants.engine.rules import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import EngineInitializer, LegacyGraphSession
from pants.init.logging import setup_logging_from_options
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.init.repro import Repro, Reproducer
from pants.init.specs_calculator import SpecsCalculator
from pants.option.arg_splitter import UnknownGoalHelp
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.reporting.reporting import Reporting
from pants.reporting.streaming_workunit_handler import StreamingWorkunitHandler
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import maybe_profiled

logger = logging.getLogger(__name__)


class LocalExiter(Exiter):
    @classmethod
    @contextmanager
    def wrap_global_exiter(cls, run_tracker, repro):
        with ExceptionSink.exiter_as(
            lambda previous_exiter: cls(run_tracker, repro, previous_exiter)
        ):
            yield

    def __init__(self, run_tracker, repro, previous_exiter: Exiter) -> None:
        self._run_tracker = run_tracker
        self._repro = repro
        super().__init__(previous_exiter)

    def exit(self, result=PANTS_SUCCEEDED_EXIT_CODE, msg=None, *args, **kwargs):
        # These strings are prepended to the existing exit message when calling the superclass .exit().
        additional_messages = []
        try:
            if not self._run_tracker.has_ended():
                if result == PANTS_SUCCEEDED_EXIT_CODE:
                    outcome = WorkUnit.SUCCESS
                elif result == PANTS_FAILED_EXIT_CODE:
                    outcome = WorkUnit.FAILURE
                else:
                    run_tracker_msg = (
                        "unrecognized exit code {} provided to {}.exit() -- "
                        "interpreting as a failure in the run tracker".format(
                            result, type(self).__name__
                        )
                    )
                    # Log the unrecognized exit code to the fatal exception log.
                    ExceptionSink.log_exception(run_tracker_msg)
                    # Ensure the unrecognized exit code message is also logged to the terminal.
                    additional_messages.append(run_tracker_msg)
                    outcome = WorkUnit.FAILURE

                self._run_tracker.set_root_outcome(outcome)
                run_tracker_result = self._run_tracker.end()
                assert (
                    result == run_tracker_result
                ), "pants exit code not correctly recorded by run tracker"
        except ValueError as e:
            # If we have been interrupted by a signal, calling .end() sometimes writes to a closed file,
            # so we just log that fact here and keep going.
            exception_string = str(e)
            ExceptionSink.log_exception(exception_string)
            additional_messages.append(exception_string)
        finally:
            if self._repro:
                # TODO: Have Repro capture the 'after' state (as a diff) as well? (in reference to the below
                # 'before' state comment)
                # NB: this writes to the logger, which is expected to still be alive if we are exiting from
                # a signal.
                self._repro.log_location_of_repro_file()

        if additional_messages:
            msg = "{}\n\n{}".format("\n".join(additional_messages), msg or "")

        super().exit(result=result, msg=msg, *args, **kwargs)


@dataclass
class LocalPantsRunner(ExceptionSink.AccessGlobalExiterMixin):
    """Handles a single pants invocation running in the process-local context.

    build_root: The build root for this run.
    options: The parsed options for this run.
    options_bootstrapper: The OptionsBootstrapper instance to use.
    build_config: The parsed build configuration for this run.
    specs: The specs for this run, i.e. either the address or filesystem specs.
    graph_session: A LegacyGraphSession instance for graph reuse.
    is_daemon: Whether or not this run was launched with a daemon graph helper.
    profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
    """

    build_root: str
    options: Options
    options_bootstrapper: OptionsBootstrapper
    build_config: BuildConfiguration
    specs: Specs
    graph_session: LegacyGraphSession
    union_membership: UnionMembership
    is_daemon: bool
    profile_path: Optional[str]
    _run_tracker: Optional[RunTracker] = None
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
    ) -> LegacyGraphSession:
        native = Native()
        native.set_panic_handler()
        graph_scheduler_helper = EngineInitializer.setup_legacy_graph(
            native, options_bootstrapper, build_config
        )

        v2_ui = options.for_global_scope().get("v2_ui", False)
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
            v2_ui,
            should_report_workunits=stream_workunits,
        )

    @classmethod
    def create(
        cls,
        env: Mapping[str, str],
        options_bootstrapper: OptionsBootstrapper,
        specs: Optional[Specs] = None,
        daemon_graph_session: Optional[LegacyGraphSession] = None,
    ) -> "LocalPantsRunner":
        """Creates a new LocalPantsRunner instance by parsing options.

        :param env: The environment (e.g. os.environ) for this run.
        :param options_bootstrapper: The OptionsBootstrapper instance to reuse.
        :param specs: The specs for this run, i.e. either the address or filesystem specs.
        :param daemon_graph_session: The graph helper for this session.
        """
        build_root = get_buildroot()

        global_options = options_bootstrapper.bootstrap_options.for_global_scope()
        # This works as expected due to the encapsulated_logger in DaemonPantsRunner and
        # we don't have to gate logging setup anymore.
        setup_logging_from_options(global_options)

        options, build_config = LocalPantsRunner.parse_options(options_bootstrapper)

        # Option values are usually computed lazily on demand,
        # but command line options are eagerly computed for validation.
        for scope in options.scope_to_flags.keys():
            options.for_scope(scope)

        # Verify configs.
        if global_options.verify_config:
            options.verify_configs(options_bootstrapper.config)

        union_membership = UnionMembership(build_config.union_rules())

        # If we're running with the daemon, we'll be handed a session from the
        # resident graph helper - otherwise initialize a new one here.
        graph_session = (
            daemon_graph_session
            if daemon_graph_session
            else cls._init_graph_session(options_bootstrapper, build_config, options)
        )

        if specs is None:
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
            is_daemon=daemon_graph_session is not None,
            profile_path=profile_path,
        )

    def set_start_time(self, start_time: Optional[float]) -> None:
        # Launch RunTracker as early as possible (before .run() is called).
        self._run_tracker = RunTracker.global_instance()

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

    def _maybe_run_v1(self, v1: bool) -> int:
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
                self._run_tracker,  # type: ignore
                self._reporting,  # type: ignore
                self.graph_session,
                self.specs,
                self._exiter,
            )
            .create()
            .run()
        )

    def _maybe_run_v2(self, v2: bool) -> int:
        # N.B. For daemon runs, @goal_rules are invoked pre-fork -
        # so this path only serves the non-daemon run mode.
        if self.is_daemon:
            return PANTS_SUCCEEDED_EXIT_CODE

        _, ambiguous_goals, v2_goals = self.options.goals_by_version
        goals = v2_goals + (ambiguous_goals if v2 else tuple())
        if self._run_tracker:
            self._run_tracker.set_v2_goal_rule_names(goals)
        if not goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        return self.graph_session.run_goal_rules(
            options_bootstrapper=self.options_bootstrapper,
            union_membership=self.union_membership,
            options=self.options,
            goals=goals,
            specs=self.specs,
        )

    @staticmethod
    def _compute_final_exit_code(*codes):
        """Returns the exit code with higher abs value in case of negative values."""
        max_code = None
        for code in codes:
            if max_code is None or abs(max_code) < abs(code):
                max_code = code
        return max_code

    def _update_stats(self):
        scheduler_session = self.graph_session.scheduler_session
        metrics = scheduler_session.metrics()
        self._run_tracker.pantsd_stats.set_scheduler_metrics(metrics)
        engine_workunits = scheduler_session.engine_workunits(metrics)
        if engine_workunits:
            self._run_tracker.report.bulk_record_workunits(engine_workunits)

    def run(self):
        global_options = self.options.for_global_scope()

        exiter = LocalExiter.wrap_global_exiter(self._run_tracker, self._repro)
        profiled = maybe_profiled(self.profile_path)

        with exiter, profiled:
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
                help_output = help_printer.print_help()
                self._exiter.exit(help_output)

            v1 = global_options.v1
            v2 = global_options.v2
            with streaming_reporter.session():
                try:
                    engine_result = self._maybe_run_v2(v2)
                    goal_runner_result = self._maybe_run_v1(v1)
                finally:
                    run_tracker_result = self._finish_run()
            final_exit_code = self._compute_final_exit_code(
                engine_result, goal_runner_result, run_tracker_result
            )
            self._exiter.exit(final_exit_code)

    def _finish_run(self):
        try:
            self._update_stats()
            return self._run_tracker.end()
        except ValueError as e:
            # Calling .end() sometimes writes to a closed file, so we return a dummy result here.
            logger.exception(e)
            return PANTS_SUCCEEDED_EXIT_CODE
