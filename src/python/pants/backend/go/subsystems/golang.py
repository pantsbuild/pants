# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os

from pants.core.util_rules.asdf import AsdfPathString
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


_DEFAULT_COMPILER_FLAGS = ("-g", "-O2")


class GolangSubsystem(Subsystem):
    options_scope = "golang"
    help = "Options for Golang support."

    class EnvironmentAware(Subsystem.EnvironmentAware):
        env_vars_used_by_options = ("PATH",)

        _go_search_paths = StrListOption(
            default=["<PATH>"],
            help=softwrap(
                f"""
                A list of paths to search for Go.

                Specify absolute paths to directories with the `go` binary, e.g. `/usr/bin`.
                Earlier entries will be searched first.

                The following special strings are supported:

                * `<PATH>`, the contents of the PATH environment variable
                * `{AsdfPathString.STANDARD}`, {AsdfPathString.STANDARD.description("Go")}
                * `{AsdfPathString.LOCAL}`, {AsdfPathString.LOCAL.description("binary")}
                """
            ),
        )
        _subprocess_env_vars = StrListOption(
            default=["LANG", "LC_CTYPE", "LC_ALL", "PATH"],
            help=softwrap(
                """
            Environment variables to set when invoking the `go` tool.
            Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
            or just `ENV_VAR` to copy the value from Pants's own environment.
            """
            ),
            advanced=True,
        )

        _cgo_tool_search_paths = StrListOption(
            default=["<PATH>"],
            help=softwrap(
                """
                A list of paths to search for tools needed by CGo (e.g., gcc, g++).

                Specify absolute paths to directories with tools needed by CGo , e.g. `/usr/bin`.
                Earlier entries will be searched first.

                The following special strings are supported:

                * `<PATH>`, the contents of the PATH environment variable
                """
            ),
        )

        cgo_gcc_binary_name = StrOption(
            default="gcc",
            advanced=True,
            help=softwrap(
                """
                Name of the tool to use to compile C code included via CGo in a Go package.
                Pants will search for the tool using the paths specified by the
                `[golang].cgo_tool_search_paths` option.
                """
            ),
        )

        cgo_gxx_binary_name = StrOption(
            default="g++",
            advanced=True,
            help=softwrap(
                """
                Name of the tool to use to compile C++ code included via CGo in a Go package.
                Pants will search for the tool using the paths specified by the
                `[golang].cgo_tool_search_paths` option.
                """
            ),
        )

        cgo_fortran_binary_name = StrOption(
            default="gfortran",
            advanced=True,
            help=softwrap(
                """
                Name of the tool to use to compile fortran code included via CGo in a Go package.
                Pants will search for the tool using the paths specified by the
                `[golang].cgo_tool_search_paths` option.
                """
            ),
        )

        external_linker_binary_name = StrOption(
            default="gcc",
            advanced=True,
            help=softwrap(
                """
                Name of the tool to use as the "external linker" when invoking `go tool link`.
                Pants will search for the tool using the paths specified by the
                `[golang].cgo_tool_search_paths` option.
                """
            ),
        )

        cgo_c_flags = StrListOption(
            default=lambda _: list(_DEFAULT_COMPILER_FLAGS),
            advanced=True,
            help=softwrap(
                """
                Compiler options used when compiling C code when Cgo is enabled. Equivalent to setting the
                CGO_CFLAGS environment variable when invoking `go`.
                """
            ),
        )

        cgo_cxx_flags = StrListOption(
            default=lambda _: list(_DEFAULT_COMPILER_FLAGS),
            advanced=True,
            help=softwrap(
                """
                Compiler options used when compiling C++ code when Cgo is enabled. Equivalent to setting the
                CGO_CXXFLAGS environment variable when invoking `go`.
                """
            ),
        )

        cgo_fortran_flags = StrListOption(
            default=lambda _: list(_DEFAULT_COMPILER_FLAGS),
            advanced=True,
            help=softwrap(
                """
                Compiler options used when compiling Fortran code when Cgo is enabled. Equivalent to setting the
                CGO_FFLAGS environment variable when invoking `go`.
                """
            ),
        )

        cgo_linker_flags = StrListOption(
            default=lambda _: list(_DEFAULT_COMPILER_FLAGS),
            advanced=True,
            help=softwrap(
                """
                Compiler options used when linking native code when Cgo is enabled. Equivalent to setting the
                CGO_LDFLAGS environment variable when invoking `go`.
                """
            ),
        )

        @property
        def raw_go_search_paths(self) -> tuple[str, ...]:
            return tuple(self._go_search_paths)

        @property
        def env_vars_to_pass_to_subprocesses(self) -> tuple[str, ...]:
            return tuple(sorted(set(self._subprocess_env_vars)))

        @memoized_property
        def cgo_tool_search_paths(self) -> tuple[str, ...]:
            def iter_path_entries():
                for entry in self._cgo_tool_search_paths:
                    if entry == "<PATH>":
                        path = self._options_env.get("PATH")
                        if path:
                            yield from path.split(os.pathsep)
                    else:
                        yield entry

            return tuple(OrderedSet(iter_path_entries()))

    minimum_expected_version = StrOption(
        default="1.17",
        help=softwrap(
            """
            The minimum Go version the distribution discovered by Pants must support.

            For example, if you set `'1.17'`, then Pants will look for a Go binary that is 1.17+,
            e.g. 1.17 or 1.18.

            You should still set the Go version for each module in your `go.mod` with the `go`
            directive.

            Do not include the patch version.
            """
        ),
    )
    tailor_go_mod_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add a `go_mod` target with the `tailor` goal wherever there is a
            `go.mod` file.
            """
        ),
        advanced=True,
    )
    tailor_package_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add a `go_package` target with the `tailor` goal in every directory with a
            `.go` file.
            """
        ),
        advanced=True,
    )
    tailor_binary_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add a `go_binary` target with the `tailor` goal in every directory with a
            `.go` file with `package main`.
            """
        ),
        advanced=True,
    )

    cgo_enabled = BoolOption(
        default=True,
        help=softwrap(
            """\
            Enable Cgo support, which allows Go and C code to interact. This option must be enabled for any
            packages making use of Cgo to actually be compiled with Cgo support.

            See https://go.dev/blog/cgo and https://pkg.go.dev/cmd/cgo for additional information about Cgo.
            """
        ),
    )

    asdf_tool_name = StrOption(
        default="go-sdk",
        help=softwrap(
            """
            The ASDF tool name to use when searching for installed Go distributions using the ASDF tool
            manager (https://asdf-vm.com/). The default value for this option is for the `go-sdk` ASDF plugin
            (https://github.com/yacchi/asdf-go-sdk.git). There are other plugins. If you wish to use one of them,
            then set this option to the ASDF tool name under which that other plugin was installed into ASDF.
            """
        ),
        advanced=True,
    )

    asdf_bin_relpath = StrOption(
        default="bin",
        help=softwrap(
            """
            The path relative to an ASDF install directory to use to find the `bin` directory within an installed
            Go distribution. The default value for this option works for the `go-sdk` ASDF plugin. Other ASDF
            plugins that install Go may have a different relative path to use.
            """
        ),
        advanced=True,
    )
