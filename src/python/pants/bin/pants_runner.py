# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import platform
import sys
import warnings
from collections.abc import Mapping
from dataclasses import dataclass

from packaging.version import Version

from pants.base.deprecated import warn_or_error
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import ExitCode
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.init.logging import initialize_stdio, stdio_destination
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.docutil import doc_url
from pants.util.osutil import get_normalized_arch_name, macos_major_version
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

# First version with working Python 3.11 support:
# https://github.com/pantsbuild/scie-pants/releases/tag/v0.12.2
# TODO: Likely still need to update scie-pants
MINIMUM_SCIE_PANTS_VERSION = Version("0.12.2")


@dataclass(frozen=True)
class PantsRunner:
    """A higher-level runner that delegates runs to either a LocalPantsRunner or
    RemotePantsRunner."""

    args: list[str]
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
            logger.debug(f"Pantsd terminating goal detected: {self.args}")

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
            logger.debug(f"Scrubbed PYTHONPATH={pythonpath} from the environment.")

    def run(self, start_time: float) -> ExitCode:
        self.scrub_pythonpath()

        options_bootstrapper = OptionsBootstrapper.create(
            args=self.args, env=self.env, allow_pantsrc=True
        )
        with warnings.catch_warnings(record=True):
            bootstrap_options = options_bootstrapper.bootstrap_options
            global_bootstrap_options = bootstrap_options.for_global_scope()

        # We enable logging here, and everything before it will be routed through regular
        # Python logging.
        stdin_fileno = sys.stdin.fileno()
        stdout_fileno = sys.stdout.fileno()
        stderr_fileno = sys.stderr.fileno()
        with (
            initialize_stdio(global_bootstrap_options),
            stdio_destination(
                stdin_fileno=stdin_fileno,
                stdout_fileno=stdout_fileno,
                stderr_fileno=stderr_fileno,
            ),
        ):
            run_via_scie = "SCIE" in os.environ
            enable_scie_warnings = "NO_SCIE_WARNING" not in os.environ
            scie_pants_version = os.environ.get("SCIE_PANTS_VERSION")

            if enable_scie_warnings:
                if not run_via_scie:
                    raise RuntimeError(
                        softwrap(
                            f"""
                            The `pants` launcher binary is now the only supported way of running Pants.
                            See {doc_url("docs/getting-started/installing-pants")} for details.
                            """
                        ),
                    )

                if run_via_scie and (
                    # either scie-pants is too old to communicate its version:
                    scie_pants_version is None
                    # or the version itself is too old:
                    or Version(scie_pants_version) < MINIMUM_SCIE_PANTS_VERSION
                ):
                    current_version_text = (
                        f"The current version of the `pants` launcher binary is {scie_pants_version}"
                        if scie_pants_version
                        else "Run `PANTS_BOOTSTRAP_VERSION=report pants` to see the current version of the `pants` launcher binary"
                    )
                    warn_or_error(
                        "2.25.0.dev0",
                        f"using a `pants` launcher binary older than {MINIMUM_SCIE_PANTS_VERSION}",
                        softwrap(
                            f"""
                            {current_version_text}, and see {doc_url("docs/getting-started/installing-pants#upgrading-pants")} for how to upgrade.
                            """
                        ),
                    )

            _validate_macos_version(global_bootstrap_options)

            # N.B. We inline imports to speed up the python thin client run, and avoids importing
            # engine types until after the runner has had a chance to set __PANTS_BIN_NAME.
            if self._should_run_with_pantsd(global_bootstrap_options):
                from pants.bin.remote_pants_runner import RemotePantsRunner

                try:
                    remote_runner = RemotePantsRunner(self.args, self.env, options_bootstrapper)
                    return remote_runner.run(start_time)
                except RemotePantsRunner.Fallback as e:
                    logger.warning(f"Client exception: {e!r}, falling back to non-daemon mode")

            from pants.bin.local_pants_runner import LocalPantsRunner

            # We only install signal handling via ExceptionSink if the run will execute in this process.
            ExceptionSink.install(
                log_location=init_workdir(global_bootstrap_options), pantsd_instance=False
            )
            runner = LocalPantsRunner.create(
                env=CompleteEnvironmentVars(self.env),
                working_dir=os.getcwd(),
                options_bootstrapper=options_bootstrapper,
            )
            return runner.run(start_time)


# for each architecture, indicate the first Pants version that doesn't support the given version of
# macOS, if it is (soon to be) unsupported:
_MACOS_VERSION_BECOMES_UNSUPPORTED_IN = {
    # macos-14 is currently oldest github hosted runner for arm
    "arm64": {
        10: "2.24.0.dev0",
        11: "2.24.0.dev0",
        12: "2.25.0.dev0",
        13: "2.25.0.dev0",
        # adding new values here should update the phrasing of the message below
    },
    # macos-13 will soon be the oldest (and only) github hosted runner for x86-64 (see https://github.com/pantsbuild/pants/issues/21333)
    "x86_64": {
        10: "2.24.0.dev0",
        11: "2.24.0.dev0",
        12: "2.25.0.dev0",
        # adding new values here should update the phrasing of the message below
    },
}


def _validate_macos_version(global_bootstrap_options: OptionValueContainer) -> None:
    """Check for running on deprecated/unsupported versions of macOS, and similar."""

    macos_version = macos_major_version()
    if macos_version is None:
        # Not macOS, no validation/deprecations required!
        return

    arch_versions = _MACOS_VERSION_BECOMES_UNSUPPORTED_IN[get_normalized_arch_name()]
    unsupported_version = arch_versions.get(macos_version)

    is_permitted_deprecated_macos_version = (
        str(macos_version) in global_bootstrap_options.allow_deprecated_macos_versions
    )

    if unsupported_version is not None and not is_permitted_deprecated_macos_version:
        warn_or_error(
            unsupported_version,
            "using Pants on older macOS",
            softwrap(
                f"""
                Recent versions of Pants only support macOS 13 and newer (on x86-64) and macOS
                14 and newer (on arm64), but this machine appears older ({platform.platform()}
                implies macOS version {macos_version}). This version also isn't permitted by your
                `[GLOBAL].allow_deprecated_macos_versions` configuration
                ({global_bootstrap_options.allow_deprecated_macos_versions}).

                Either upgrade your operating system(s), or silence this message (and thus opt-in to
                potential breakage) by adding "{macos_version}" to the
                `[GLOBAL].allow_deprecated_macos_versions` list.

                If you have questions or concerns about this, please reach out to us at
                {doc_url("community/getting-help")}.
                """
            ),
        )
