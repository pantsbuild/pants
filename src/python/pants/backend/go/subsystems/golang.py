# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class GolangSubsystem(Subsystem):
    options_scope = "golang"
    help = "Options for Golang support."

    _go_search_paths = StrListOption(
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Go.

            Specify absolute paths to directories with the `go` binary, e.g. `/usr/bin`.
            Earlier entries will be searched first.

            The following special strings are supported:

              * `<PATH>`, the contents of the PATH environment variable
              * `<ASDF>`, all Go versions currently configured by ASDF \
                  `(asdf shell, ${HOME}/.tool-versions)`, with a fallback to all installed versions
              * `<ASDF_LOCAL>`, the ASDF interpreter with the version in BUILD_ROOT/.tool-versions
            """
        ),
    )
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

    @property
    def raw_go_search_paths(self) -> tuple[str, ...]:
        return tuple(self._go_search_paths)

    @property
    def env_vars_to_pass_to_subprocesses(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._subprocess_env_vars)))
