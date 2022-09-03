# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class CCOptions:
    c_compile_options = StrListOption(
        default=["-std=c11"],
        help=softwrap(
            """
            Flags passed to the C compiler.
            These flags are merged with the target-level defines, with the target-level flags taking precedence.
            """
        ),
    )

    c_defines = StrListOption(
        default=None,
        help=softwrap(
            """
            A list of strings to define in the C preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with the target-level definitions taking precedence.
            """
        ),
    )

    cpp_compile_options = StrListOption(
        default=["-std=c++11"],
        help=softwrap(
            """
            Flags passed to the C++ compiler.
            These flags are merged with the target-level defines, with the target-level flags taking precedence.
            """
        ),
    )

    cpp_defines = StrListOption(
        default=None,
        help=softwrap(
            """
            A list of strings to define in the C++ preprocessor. Will be prefixed by -D at the command line.
            These defines are merged with the target-level defines, with the target-level definitions taking precedence.
            """
        ),
    )


class ExternalCCSubsystem(TemplatedExternalTool, CCOptions):
    options_scope = "cc-external"
    name = "cc-external"
    help = """Options for downloaded CC toolchain support."""

    c_executable = StrOption(
        default="gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc",
        help=softwrap(
            """
            The relative path to the C compiler binary from the downloaded source.
            E.g. For the ARM gcc-rm toolchain, this value would be: `gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc`
            """
        ),
    )

    cpp_executable = StrOption(
        default="gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++",
        help=softwrap(
            """
            The relative path to the C++ compiler binary from the downloaded source.
            E.g. For the ARM gcc-rm toolchain, this value would be: `gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++`
            """
        ),
    )

    default_version = "10.3-2021.10"
    default_url_template = "https://developer.arm.com/-/media/Files/downloads/gnu-rm/{version}/gcc-arm-none-eabi-{version}-{platform}.tar.bz2"
    default_url_platform_mapping = {
        # "macos_arm64": "darwin_arm64",
        "macos_x86_64": "mac",
        # "linux_x86_64": "linux_amd64",
    }
    default_known_versions = [
        "10.3-2021.10|macos_x86_64|fb613dacb25149f140f73fe9ff6c380bb43328e6bf813473986e9127e2bc283b|158961466",
    ]


class CCSubsystem(Subsystem, CCOptions):
    options_scope = "cc"
    name = "cc"
    help = """Options for system CC toolchain support."""

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
