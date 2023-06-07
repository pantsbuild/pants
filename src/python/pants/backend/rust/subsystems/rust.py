# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os

from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class RustSubsystem(Subsystem):
    options_scope = "rust"
    help = "Options for Rust support."

    toolchain = StrOption(
        "--toolchain",
        default="stable",
        help=softwrap(
            """
            Name of a Rust toolchain to use for all builds. The toolchain name will be provided to
            Rustup to find the Toolchain.
            """
        ),
    )

    _rustup_search_paths = StrListOption(
        "--rustup-search-paths",
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Rustup.

            Specify absolute paths to directories with the `rustup` binary, e.g. `/usr/bin`.
            Earlier entries will be searched first.
            The special string '<PATH>' will expand to the contents of the PATH env var.
            """
        ),
    )

    def rustup_search_paths(self, env) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._rustup_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))
