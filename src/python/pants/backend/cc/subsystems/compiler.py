# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterable

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class CCOptions:
    include_directories = StrListOption(
        default=[],
        help=softwrap(
            """
            A list of include directories passed to the compiler. Will be prefixed by -I at the command line.
            These flags are merged with the target-level includes, with the target-level includes taking precedence.
            """
        ),
    )

    c_compiler_flags = StrListOption(
        default=["-std=c11"],
        help=softwrap(
            """
            Flags passed to the C compiler.
            These flags are merged with the target-level defines, with the target-level flags taking precedence.
            """
        ),
    )

    c_definitions = StrListOption(
        default=None,
        help=softwrap(
            """
            A list of strings to define in the C preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with the target-level definitions taking precedence.
            """
        ),
    )

    cxx_compiler_flags = StrListOption(
        default=["-std=c++11"],
        help=softwrap(
            """
            Flags passed to the C++ compiler.
            These flags are merged with the target-level defines, with the target-level flags taking precedence.
            """
        ),
    )

    cxx_definitions = StrListOption(
        default=None,
        help=softwrap(
            """
            A list of strings to define in the C++ preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with the target-level definitions taking precedence.
            """
        ),
    )


class CCSubsystem(Subsystem, CCOptions):
    options_scope = "cc"
    name = "cc"
    help = """Options for a system-discovered `cc` toolchain."""

    c_executable = StrListOption(
        default=["clang", "gcc"],
        help=softwrap(
            """
            A list of binary names for the C compiler (in the `search_paths`).
            The list is searched in order until a compiler is found.
            """
        ),
    )

    cxx_executable = StrListOption(
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


class ExternalCCSubsystem(TemplatedExternalTool, CCOptions):
    options_scope = "cc-external"
    name = "cc-external"
    help = """Options for downloaded `cc` toolchain."""

    c_executable = StrOption(
        default="",
        help=softwrap(
            """
            The relative path to the C compiler binary from the downloaded source.
            E.g. For the ARM gcc-rm toolchain, this value would be: `gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc`
            """
        ),
    )

    cxx_executable = StrOption(
        default="",
        help=softwrap(
            """
            The relative path to the C++ compiler binary from the downloaded source.
            E.g. For the ARM gcc-rm toolchain, this value would be: `gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++`
            """
        ),
    )

    # TODO: Maybe put the ARM compiler in here?
    default_version = ""
    default_url_template = ""
    default_url_platform_mapping: dict[str, str] = {}
    default_known_versions: list[str] = []


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *CCSubsystem.rules(),
        *ExternalCCSubsystem.rules(),
    )
