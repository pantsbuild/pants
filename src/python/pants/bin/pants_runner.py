# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from typing import List, Mapping

from pants.base.deprecated import resolve_conflicting_options
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import ExitCode
from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.init.logging import setup_logging
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import GLOBAL_SCOPE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PantsRunner:
    """A higher-level runner that delegates runs to either a LocalPantsRunner or
    RemotePantsRunner."""

    args: List[str]
    env: Mapping[str, str]

    # This could be a bootstrap option, but it's preferable to keep these very limited to make it
    # easier to make the daemon the default use case. Once the daemon lifecycle is stable enough we
    # should be able to avoid needing to kill it at all.
    def will_terminate_pantsd(self) -> bool:
        _DAEMON_KILLING_GOALS = frozenset(["kill-pantsd", "clean-all"])
        return not frozenset(self.args).isdisjoint(_DAEMON_KILLING_GOALS)

    def _should_run_with_pantsd(self, global_bootstrap_options: OptionValueContainer) -> bool:
        # The parent_build_id option is set only for pants commands (inner runs)
        # that were called by other pants command.
        # Inner runs should never be run with pantsd.
        # See https://github.com/pantsbuild/pants/issues/7881 for context.
        is_inner_run = global_bootstrap_options.parent_build_id is not None
        terminate_pantsd = self.will_terminate_pantsd()

        if terminate_pantsd:
            logger.debug("Pantsd terminating goal detected: {}".format(self.args))

        # If we want concurrent pants runs, we can't have pantsd enabled.
        pantsd_toggle = resolve_conflicting_options(
            old_option="enable_pantsd",
            new_option="pantsd",
            old_scope=GLOBAL_SCOPE,
            new_scope=GLOBAL_SCOPE,
            old_container=global_bootstrap_options,
            new_container=global_bootstrap_options,
        )
        return (
            pantsd_toggle
            and not terminate_pantsd
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

    def run(self, start_time: float) -> ExitCode:
        self.scrub_pythonpath()

        options_bootstrapper = OptionsBootstrapper.create(env=self.env, args=self.args)
        bootstrap_options = options_bootstrapper.bootstrap_options
        global_bootstrap_options = bootstrap_options.for_global_scope()

        # Initialize the workdir early enough to ensure that logging has a destination.
        workdir_src = init_workdir(global_bootstrap_options)
        ExceptionSink.reset_log_location(workdir_src)

        # We enable logging here, and everything before it will be routed through regular
        # Python logging.
        setup_logging(global_bootstrap_options)

        ExceptionSink.reset_should_print_backtrace_to_terminal(
            global_bootstrap_options.print_exception_stacktrace
        )

        if self._should_run_with_pantsd(global_bootstrap_options):
            try:
                return RemotePantsRunner(self.args, self.env, options_bootstrapper).run(start_time)
            except RemotePantsRunner.Fallback as e:
                logger.warning("Client exception: {!r}, falling back to non-daemon mode".format(e))

        # N.B. Inlining this import speeds up the python thin client run by about 100ms.
        from pants.bin.local_pants_runner import LocalPantsRunner

        runner = LocalPantsRunner.create(env=self.env, options_bootstrapper=options_bootstrapper)
        return runner.run(start_time)
