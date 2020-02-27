# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from contextlib import contextmanager
from typing import List, Mapping, Optional, Tuple

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, Exiter
from pants.base.specs import Specs
from pants.base.workunit import WorkUnit
from pants.bin.goal_runner import GoalRunner
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.native import Native
from pants.engine.rules import UnionMembership
from pants.engine.scheduler import SchedulerSession
from pants.goal.run_tracker import RunTracker
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import EngineInitializer, LegacyGraphSession
from pants.init.logging import setup_logging_from_options
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.init.repro import Reproducer
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


class LocalPantsRunner(ExceptionSink.AccessGlobalExiterMixin):
    """Handles a single pants invocation running in the process-local context."""

    @staticmethod
    def parse_options(
        args: List[str],
        env: Mapping[str, str],
        options_bootstrapper: Optional[OptionsBootstrapper] = None,
    ) -> Tuple[Options, BuildConfiguration, OptionsBootstrapper]:
        options_bootstrapper = options_bootstrapper or OptionsBootstrapper.create(
            args=args, env=env
        )
        build_config = BuildConfigInitializer.get(options_bootstrapper)
        options = OptionsInitializer.create(options_bootstrapper, build_config)
        return options, build_config, options_bootstrapper

    @staticmethod
    def _maybe_init_graph_session(
        graph_session: Optional[LegacyGraphSession],
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        options: Options,
    ) -> Tuple[LegacyGraphSession, SchedulerSession]:
        if not graph_session:
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
            graph_session = graph_scheduler_helper.new_session(
                zipkin_trace_v2,
                RunTracker.global_instance().run_id,
                v2_ui,
                should_report_workunits=stream_workunits,
            )
        return graph_session, graph_session.scheduler_session

    @staticmethod
    def _maybe_init_specs(
        specs: Optional[Specs],
        graph_session: LegacyGraphSession,
        options: Options,
        build_root: str,
    ) -> Specs:
        if specs:
            return specs

        global_options = options.for_global_scope()
        return SpecsCalculator.create(
            options=options,
            build_root=build_root,
            session=graph_session.scheduler_session,
            exclude_patterns=tuple(global_options.exclude_target_regexp),
            tags=tuple(global_options.tag),
        )

    @classmethod
    def create(
        cls,
        args: List[str],
        env: Mapping[str, str],
        specs: Optional[Specs] = None,
        daemon_graph_session: Optional[LegacyGraphSession] = None,
        options_bootstrapper: Optional[OptionsBootstrapper] = None,
    ) -> "LocalPantsRunner":
        """Creates a new LocalPantsRunner instance by parsing options.

        :param args: The arguments (e.g. sys.argv) for this run.
        :param env: The environment (e.g. os.environ) for this run.
        :param specs: The specs for this run, i.e. either the address or filesystem specs.
        :param daemon_graph_session: The graph helper for this session.
        :param options_bootstrapper: The OptionsBootstrapper instance to reuse.
        """
        build_root = get_buildroot()

        options, build_config, options_bootstrapper = cls.parse_options(
            args, env, options_bootstrapper=options_bootstrapper,
        )
        global_options = options.for_global_scope()
        # This works as expected due to the encapsulated_logger in DaemonPantsRunner and
        # we don't have to gate logging setup anymore.
        setup_logging_from_options(global_options)

        # Option values are usually computed lazily on demand,
        # but command line options are eagerly computed for validation.
        for scope in options.scope_to_flags.keys():
            options.for_scope(scope)

        # Verify configs.
        if global_options.verify_config:
            options_bootstrapper.verify_configs_against_options(options)

        union_membership = UnionMembership(build_config.union_rules())

        # If we're running with the daemon, we'll be handed a session from the
        # resident graph helper - otherwise initialize a new one here.
        graph_session, scheduler_session = cls._maybe_init_graph_session(
            daemon_graph_session, options_bootstrapper, build_config, options
        )

        specs = cls._maybe_init_specs(specs, graph_session, options, build_root)

        profile_path = env.get("PANTS_PROFILE")

        return cls(
            build_root=build_root,
            options=options,
            options_bootstrapper=options_bootstrapper,
            build_config=build_config,
            specs=specs,
            graph_session=graph_session,
            scheduler_session=scheduler_session,
            union_membership=union_membership,
            is_daemon=daemon_graph_session is not None,
            profile_path=profile_path,
        )

    def __init__(
        self,
        build_root: str,
        options: Options,
        options_bootstrapper: OptionsBootstrapper,
        build_config: BuildConfiguration,
        specs: Specs,
        graph_session: LegacyGraphSession,
        scheduler_session: SchedulerSession,
        union_membership: UnionMembership,
        is_daemon: bool,
        profile_path: Optional[str],
    ) -> None:
        """
        :param build_root: The build root for this run.
        :param options: The parsed options for this run.
        :param options_bootstrapper: The OptionsBootstrapper instance to use.
        :param build_config: The parsed build configuration for this run.
        :param specs: The specs for this run, i.e. either the address or filesystem specs.
        :param graph_session: A LegacyGraphSession instance for graph reuse.
        :param is_daemon: Whether or not this run was launched with a daemon graph helper.
        :param profile_path: The profile path - if any (from from the `PANTS_PROFILE` env var).
        """
        self._build_root = build_root
        self._options = options
        self._options_bootstrapper = options_bootstrapper
        self._build_config = build_config
        self._specs = specs
        self._graph_session = graph_session
        self._scheduler_session = scheduler_session
        self._union_membership = union_membership
        self._is_daemon = is_daemon
        self._profile_path = profile_path

        self._run_start_time = None
        self._run_tracker = None
        self._reporting = None
        self._repro = None
        self._global_options = options.for_global_scope()

    def set_start_time(self, start_time):
        # Launch RunTracker as early as possible (before .run() is called).
        self._run_tracker = RunTracker.global_instance()

        # Propagates parent_build_id to pants runs that may be called from this pants run.
        os.environ["PANTS_PARENT_BUILD_ID"] = self._run_tracker.run_id

        self._reporting = Reporting.global_instance()

        self._run_start_time = start_time
        self._reporting.initialize(
            self._run_tracker, self._options, start_time=self._run_start_time
        )

        spec_parser = CmdLineSpecParser(get_buildroot())
        specs = [spec_parser.parse_spec(spec).to_spec_string() for spec in self._options.specs]
        # Note: This will not include values from `--owner-of` or `--changed-*` flags.
        self._run_tracker.run_info.add_info("specs_from_command_line", specs, stringify=False)

        # Capture a repro of the 'before' state for this build, if needed.
        self._repro = Reproducer.global_instance().create_repro()
        if self._repro:
            self._repro.capture(self._run_tracker.run_info.get_as_dict())

    def run(self):
        with LocalExiter.wrap_global_exiter(self._run_tracker, self._repro), maybe_profiled(
            self._profile_path
        ):
            self._run()

    def _maybe_handle_help(self):
        """Handle requests for `help` information."""
        if self._options.help_request:
            help_printer = HelpPrinter(
                options=self._options, union_membership=self._union_membership
            )
            result = help_printer.print_help()
            return result

    def _maybe_run_v1(self):
        v1_goals, ambiguous_goals, _ = self._options.goals_by_version
        if not self._global_options.v1:
            if v1_goals:
                HelpPrinter(
                    options=self._options,
                    help_request=UnknownGoalHelp(v1_goals),
                    union_membership=self._union_membership,
                ).print_help()
                return PANTS_FAILED_EXIT_CODE
            return PANTS_SUCCEEDED_EXIT_CODE

        if not v1_goals and not ambiguous_goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        TargetAdaptor._use_v1_targets = False

        # Setup and run GoalRunner.
        return (
            GoalRunner.Factory(
                self._build_root,
                self._options_bootstrapper,
                self._options,
                self._build_config,
                self._run_tracker,
                self._reporting,
                self._graph_session,
                self._specs,
                self._exiter,
            )
            .create()
            .run()
        )

    def _maybe_run_v2(self):
        # N.B. For daemon runs, @goal_rules are invoked pre-fork -
        # so this path only serves the non-daemon run mode.
        if self._is_daemon:
            return PANTS_SUCCEEDED_EXIT_CODE

        _, ambiguous_goals, v2_goals = self._options.goals_by_version
        goals = v2_goals + (ambiguous_goals if self._global_options.v2 else tuple())
        self._run_tracker.set_v2_goal_rule_names(goals)
        if not goals:
            return PANTS_SUCCEEDED_EXIT_CODE

        return self._graph_session.run_goal_rules(
            options_bootstrapper=self._options_bootstrapper,
            union_membership=self._union_membership,
            options=self._options,
            goals=goals,
            specs=self._specs,
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
        metrics = self._scheduler_session.metrics()
        self._run_tracker.pantsd_stats.set_scheduler_metrics(metrics)
        engine_workunits = self._scheduler_session.engine_workunits(metrics)
        if engine_workunits:
            self._run_tracker.report.bulk_record_workunits(engine_workunits)

    def _run(self):
        global_options = self._options.for_global_scope()

        streaming_handlers = global_options.streaming_workunits_handlers
        report_interval = global_options.streaming_workunits_report_interval
        callbacks = Subsystem.get_streaming_workunit_callbacks(streaming_handlers)
        streaming_reporter = StreamingWorkunitHandler(
            self._scheduler_session, callbacks=callbacks, report_interval_seconds=report_interval
        )

        help_output = self._maybe_handle_help()
        if help_output is not None:
            self._exiter.exit(help_output)

        with streaming_reporter.session():
            try:
                engine_result = self._maybe_run_v2()
                goal_runner_result = self._maybe_run_v1()
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
