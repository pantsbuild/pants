# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import warnings
from dataclasses import dataclass
from typing import List, Mapping

from pants.base.deprecated import deprecated_conditional
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import ExitCode
from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.init.logging import setup_logging, setup_warning_filtering
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper

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
        terminate_pantsd = self.will_terminate_pantsd()

        if terminate_pantsd:
            logger.debug("Pantsd terminating goal detected: {}".format(self.args))

        # If we want concurrent pants runs, we can't have pantsd enabled.
        return (
            global_bootstrap_options.pantsd
            and not terminate_pantsd
            and not global_bootstrap_options.concurrent
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

        options_bootstrapper = OptionsBootstrapper.create(
            env=self.env, args=self.args, allow_pantsrc=True
        )
        with warnings.catch_warnings(record=True):
            bootstrap_options = options_bootstrapper.bootstrap_options
            global_bootstrap_options = bootstrap_options.for_global_scope()

        # Initialize the workdir early enough to ensure that logging has a destination.
        workdir_src = init_workdir(global_bootstrap_options)
        ExceptionSink.reset_log_location(workdir_src)

        setup_warning_filtering(global_bootstrap_options.ignore_pants_warnings or [])
        # We enable logging here, and everything before it will be routed through regular
        # Python logging.
        setup_logging(global_bootstrap_options, stderr_logging=True)

        deprecated_conditional(
            lambda: sys.version_info[:2] == (3, 6),
            entity_description="running Pants with Python 3.6",
            removal_version="2.2.0.dev0",
            hint_message=(
                "Pants 2.2+ will require running the tool with Python 3.7 or 3.8. Update your "
                "`./pants` script by running `curl -L -o ./pants "
                "https://raw.githubusercontent.com/pantsbuild/setup/2f079cbe4fc6a1d9d87decba51f19d7689aee69e/pants`"
                "\n\n(Note: this does not impact what Python interpreter your own code uses, "
                "outside of Pants plugin code.)"
            ),
        )

        if self._should_run_with_pantsd(global_bootstrap_options):
            try:
                remote_runner = RemotePantsRunner(self.args, self.env, options_bootstrapper)
                return remote_runner.run()
            except RemotePantsRunner.Fallback as e:
                logger.warning("Client exception: {!r}, falling back to non-daemon mode".format(e))

        # N.B. Inlining this import speeds up the python thin client run by about 100ms.
        from pants.bin.local_pants_runner import LocalPantsRunner

        runner = LocalPantsRunner.create(env=self.env, options_bootstrapper=options_bootstrapper)
        return runner.run(start_time)
