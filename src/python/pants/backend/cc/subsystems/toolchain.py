# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

from typing_extensions import Literal

from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, Rule, collect_rules, rule, rule_helper
from pants.engine.unions import UnionRule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class CCSubsystem(Subsystem):
    # TODO: Consider splitting this into a C and C++ subsystem if it gets unwieldy
    options_scope = "cc"
    name = "cc"
    help = """TODO"""

    c_executable = StrListOption(
        default=["clang", "gcc"],
        help=softwrap(
            """
            A list of binary names for the C compiler (in the `search_paths`).

            The list is searched in order until a compiler is found.
            """
        ),
    )

    cpp_executable = StrListOption(
        default=["clang++", "g++"],
        help=softwrap(
            """
            A list of binary names for the C compiler (in the `search_paths`).

            The list is searched in order until a compiler is found.
            """
        ),
    )

    search_paths = StrListOption(
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for CC toolchain binaries.

            Specify absolute paths to directories, e.g. `/usr/bin`.
            Earlier entries will be searched first.

            The following special strings are supported:

              * `<PATH>`, the contents of the PATH environment variable
            """
        ),
    )

    c_compile_options = StrListOption(
        default=["-std=c11"],
        help=softwrap(
            """
            Flags passed to the C++ compiler.
            These flags are merged with the toolchain-level defines, with target-level flags taking precedence.
            """
        ),
    )

    c_defines = StrListOption(
        default=[""],
        help=softwrap(
            """
            A list of strings to define in the C preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with target-level definitions taking precedence.
            """
        ),
    )

    cpp_compile_options = StrListOption(
        default=["-std=c++11"],
        help=softwrap(
            """
            Flags passed to the C++ compiler.
            These flags are merged with the toolchain-level defines, with target-level flags taking precedence.
            """
        ),
    )

    cpp_defines = StrListOption(
        default=[""],
        help=softwrap(
            """
            A list of strings to define in the C++ preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with target-level definitions taking precedence.
            """
        ),
    )


# TODO: What's a good way to grab the compiler (filename or target language) and linker (... language of compiled objects?)
@dataclass(frozen=True)
class CCToolchainRequest:
    language: Literal["c", "c++"]


@dataclass(frozen=True)
class CCToolchain:
    """A configured C/C++ toolchain for the current platform."""

    compiler: BinaryPath
    compile_flags: tuple[str, ...] = ()
    compile_defines: tuple[str, ...] = ()
    link_flags: tuple[str, ...] = ()

    def __post_init__(self):
        # TODO: Should this error out to notify the user of a mistake? Or silently handle
        # Or just ensure all defines have -D right now?
        if self.compile_defines:
            sanitized_defines = [define.lstrip("-D") for define in self.compile_defines]
            object.__setattr__(self, "compile_defines", tuple(sanitized_defines))

    @property
    def compile_argv(self) -> tuple[str, ...]:
        return (
            self.compiler.path,
            "-v",
            *self.compile_defines,
            *self.compile_flags,
        )

    @property
    def link_argv(self) -> tuple[str, ...]:
        return (self.compiler.path, "-v", *self.link_flags)


@rule_helper
async def _executable_path(binary_names: Iterable[str], search_paths: Iterable[str]) -> BinaryPath:
    for name in binary_names:
        binary_paths = await Get(
            BinaryPaths,
            BinaryPathRequest(
                binary_name=name,
                search_path=search_paths,
                test=BinaryPathTest(args=["-v"]),
            ),
        )

        if not binary_paths or not binary_paths.first_path:
            continue
        return binary_paths.first_path

    raise BinaryNotFoundError(f"Could not find any of '{binary_names}' in any of {search_paths}.")


@rule(desc="Setup the CC Toolchain", level=LogLevel.DEBUG)
async def setup_cc_toolchain(subsystem: CCSubsystem, request: CCToolchainRequest) -> CCToolchain:
    # Sanitize the search paths in case the "<PATH>" is specified
    raw_search_paths = list(subsystem.search_paths)
    if "<PATH>" in raw_search_paths:
        i = raw_search_paths.index("<PATH>")
        env = await Get(Environment, EnvironmentRequest(["PATH"]))
        system_path = env.get("PATH", "")
        raw_search_paths[i : i + 1] = system_path.split(os.pathsep)

    search_paths = tuple(OrderedSet(raw_search_paths))

    # Populate the toolchain for C or C++ accordingly
    if request.language == "c++":
        cpp_executable = await _executable_path(tuple(subsystem.cpp_executable), search_paths)
        return CCToolchain(
            cpp_executable,
            compile_flags=tuple(subsystem.cpp_compile_options),
            compile_defines=tuple(subsystem.cpp_defines),
        )
    else:
        c_executable = await _executable_path(tuple(subsystem.c_executable), search_paths)
        return CCToolchain(
            c_executable,
            compile_flags=tuple(subsystem.c_compile_options),
            compile_defines=tuple(subsystem.c_defines),
        )


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
