# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import cast

from pants.engine.environment import Environment
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.ordered_set import OrderedSet


class ShellSetup(Subsystem):
    options_scope = "shell-setup"
    help = "Options for Pants's Shell support."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--executable-search-paths",
            advanced=True,
            type=list,
            default=["<PATH>"],
            metavar="<binary-paths>",
            help=(
                "The PATH value that will be used to find shells and to run certain processes "
                "like the shunit2 test runner.\n\n"
                'The special string "<PATH>" will expand to the contents of the PATH env var.'
            ),
        )
        register(
            "--dependency-inference",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "Infer Shell dependencies on other Shell files by analyzing `source` statements."
            ),
        )

    @memoized_method
    def executable_search_path(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.executable_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))

    @property
    def dependency_inference(self) -> bool:
        return cast(bool, self.options.dependency_inference)
