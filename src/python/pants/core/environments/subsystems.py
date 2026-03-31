# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.global_options import GlobalOptions
from pants.option.option_types import DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text, softwrap


class EnvironmentsSubsystem(Subsystem):
    options_scope = "environments-preview"
    help = help_text(
        """
        A highly experimental subsystem to allow setting environment variables and executable
        search paths for different environments, e.g. macOS vs. Linux.
        """
    )

    names = DictOption[str](
        help=softwrap(
            """
            A mapping of logical names to addresses to environment targets. For example:

                [environments-preview.names]
                linux_local = "//:linux_env"
                macos_local = "//:macos_env"
                centos6 = "//:centos6_docker_env"
                linux_ci = "build-support:linux_ci_env"
                macos_ci = "build-support:macos_ci_env"

            To use an environment for a given target, specify the name in the `environment` field
            on that target. Pants will consume the environment target at the address mapped from
            that name.

            Pants will ignore any environment targets that are not given a name via this option.
            """
        )
    )

    def remote_execution_used_globally(self, global_options: GlobalOptions) -> bool:
        """If the environments mechanism is not used, `--remote-execution` toggles remote execution
        globally."""
        return not self.names and global_options.remote_execution
