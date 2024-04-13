# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class ShellSetup(Subsystem):
    options_scope = "shell-setup"
    help = "Options for Pants's Shell support."

    dependency_inference = BoolOption(
        default=True,
        help="Infer Shell dependencies on other Shell files by analyzing `source` statements.",
        advanced=True,
    )
    tailor = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `shell_sources` and `shunit2_tests` targets with
            the `tailor` goal."""
        ),
        advanced=True,
    )

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find shells
            and to run certain processes like the shunit2 test runner.
            """
        )
