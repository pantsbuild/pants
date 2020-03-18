# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
from typing import List, Mapping, Optional

from pants.base.exception_sink import ExceptionSink
from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.init.logging import init_rust_logger, setup_logging_to_stderr
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper

logger = logging.getLogger(__name__)


class PantsRunner(ExceptionSink.AccessGlobalExiterMixin):
    """A higher-level runner that delegates runs to either a LocalPantsRunner or
    RemotePantsRunner."""

    def __init__(
        self,
        args: Optional[List[str]] = None,
        env: Optional[Mapping[str, str]] = None,
        start_time: Optional[float] = None,
    ) -> None:
        """
        :param args: The arguments (sys.argv) for this run. (Optional, default: sys.argv)
        :param env: The environment for this run. (Optional, default: os.environ)
        """
        self._args = args or sys.argv
        self._env = env or os.environ
        self._start_time = start_time

    # This could be a bootstrap option, but it's preferable to keep these very limited to make it
    # easier to make the daemon the default use case. Once the daemon lifecycle is stable enough we
    # should be able to avoid needing to kill it at all.
    _DAEMON_KILLING_GOALS = frozenset(["kill-pantsd", "clean-all"])

    def will_terminate_pantsd(self) -> bool:
        return not frozenset(self._args).isdisjoint(self._DAEMON_KILLING_GOALS)

    def _enable_rust_logging(self, global_bootstrap_options: OptionValueContainer) -> None:
        log_level = global_bootstrap_options.level
        init_rust_logger(log_level, global_bootstrap_options.log_show_rust_3rdparty)
        setup_logging_to_stderr(logging.getLogger(None), log_level)

    def _should_run_with_pantsd(self, global_bootstrap_options: OptionValueContainer) -> bool:
        # The parent_build_id option is set only for pants commands (inner runs)
        # that were called by other pants command.
        # Inner runs should never be run with pantsd.
        # See https://github.com/pantsbuild/pants/issues/7881 for context.
        is_inner_run = global_bootstrap_options.parent_build_id is not None

        # If we want concurrent pants runs, we can't have pantsd enabled.
        return (
            global_bootstrap_options.enable_pantsd
            and not self.will_terminate_pantsd()
            and not global_bootstrap_options.concurrent
            and not is_inner_run
        )

    @staticmethod
    def scrub_pythonpath() -> None:
        # Do not propagate any PYTHONPATH that happens to have been set in our environment
        # to our subprocesses.
        # Note that don't warn (but still scrub) if RUNNING_PANTS_FROM_SOURCES is set. This allows
        # scripts that run pants directly from sources, and therefore must set PYTHONPATH, to mute
        # this warning.
        pythonpath = os.environ.pop("PYTHONPATH", None)
        if pythonpath and not os.environ.pop("RUNNING_PANTS_FROM_SOURCES", None):
            logger.warning(f"Scrubbed PYTHONPATH={pythonpath} from the environment.")

    def run(self):
        self.scrub_pythonpath()

        options_bootstrapper = OptionsBootstrapper.create(env=self._env, args=self._args)
        bootstrap_options = options_bootstrapper.bootstrap_options
        global_bootstrap_options = bootstrap_options.for_global_scope()

        # Initialize the workdir early enough to ensure that logging has a destination.
        workdir_src = init_workdir(global_bootstrap_options)
        ExceptionSink.reset_log_location(workdir_src)

        # We enable Rust logging here,
        # and everything before it will be routed through regular Python logging.
        self._enable_rust_logging(global_bootstrap_options)

        ExceptionSink.reset_should_print_backtrace_to_terminal(
            global_bootstrap_options.print_exception_stacktrace
        )
        ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

        if self._should_run_with_pantsd(global_bootstrap_options):
            try:
                return RemotePantsRunner(
                    self._exiter, self._args, self._env, options_bootstrapper
                ).run()
            except RemotePantsRunner.Fallback as e:
                logger.warning(
                    "caught client exception: {!r}, falling back to non-daemon mode".format(e)
                )

        # N.B. Inlining this import speeds up the python thin client run by about 100ms.
        from pants.bin.local_pants_runner import LocalPantsRunner

        if self.will_terminate_pantsd():
            logger.debug("Pantsd terminating goal detected: {}".format(self._args))

        runner = LocalPantsRunner.create(
            self._args, self._env, options_bootstrapper=options_bootstrapper
        )
        runner.set_start_time(self._start_time)
        return runner.run()
