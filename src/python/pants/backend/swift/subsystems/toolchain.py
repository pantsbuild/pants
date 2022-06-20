# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class SwiftSubsystem(Subsystem):
    options_scope = "swift"
    name = "swift"
    help = softwrap(
        """
        The Swift programming language (https://www.swift.org/).
        Compilation occurs via the underlying LLVM front-end. ie. "swift-frontend -frontend", through `swiftc`
        See https://www.swift.org/swift-compiler/ for more information.
        """
    )

    # TODO: Add in a later implementation step
    # args = ArgsListOption(
    #     example="-target x86_64-apple-macosx12.0",
    #     extra_help=softwrap(
    #     """
    #     Arguments will be passed to the swiftc binary during compilation-time.
    #     Refer to `swiftc --help` for the options supported by swiftc.
    #     """
    #     ),
    # )

    _swiftc_search_paths = StrListOption(
        "--swiftc-search-paths",
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Swift.

            Specify absolute paths to directories with the `swiftc` binary, e.g. `/usr/bin`.
            Earlier entries will be searched first.

            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
    )

    def swiftc_search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._swiftc_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))


@dataclass(frozen=True)
class SwiftToolchain:
    """A configured swift toolchain for the current platform."""

    exe: str

    # TODO: Expose common settings in a later implementation
    # sdk: str #
    # target: str
    # linker_options: list[str] = []


@rule(desc="Setup the Swift Toolchain", level=LogLevel.DEBUG)
async def setup_swift_toolchain(swift: SwiftSubsystem) -> SwiftToolchain:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = swift.swiftc_search_paths(env)
    swiftc_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="swiftc",
            search_path=search_paths,
            test=BinaryPathTest(args=["--version"]),
        ),
    )
    if not swiftc_paths or not swiftc_paths.first_path:
        raise BinaryNotFoundError(
            "Cannot find any `swiftc` binaries using the option "
            f"`[swift].swiftc_search_paths`: {list(search_paths)}\n\n"
            "To fix, please install Swift (https://www.swift.org/download/)"
            "and ensure that it is discoverable via `[swift].swiftc_search_paths`."
        )
    return SwiftToolchain(exe=swiftc_paths.first_path.path)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
