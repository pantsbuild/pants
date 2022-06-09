# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.engine.environment import Environment
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class ShellSetup(Subsystem):
    options_scope = "shell-setup"
    help = "Options for Pants's Shell support."

    _executable_search_path = StrListOption(
        "--executable-search-paths",
        default=["<PATH>"],
        help=softwrap(
            """
            The PATH value that will be used to find shells and to run certain processes
            like the shunit2 test runner.

            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
        advanced=True,
        metavar="<binary-paths>",
    )
    dependency_inference = BoolOption(
        "--dependency-inference",
        default=True,
        help="Infer Shell dependencies on other Shell files by analyzing `source` statements.",
        advanced=True,
    )
    tailor = BoolOption(
        "--tailor",
        default=True,
        help=softwrap(
            """
            If true, add `shell_sources` and `shunit2_tests` targets with
            the `tailor` goal."""
        ),
        advanced=True,
    )

    @memoized_method
    def executable_search_path(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._executable_search_path:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))
