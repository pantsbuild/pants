# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os

from pants.engine.environment import Environment
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class ApacheThriftSubsystem(Subsystem):
    options_scope = "apache-thrift"
    help = "Apache Thrift IDL compiler (https://thrift.apache.org/)."

    _thrift_search_paths = StrListOption(
        "--thrift-search-paths",
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Thrift.

            Specify absolute paths to directories with the `thrift` binary, e.g. `/usr/bin`.
            Earlier entries will be searched first.

            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
    )
    expected_version = StrOption(
        "--expected-version",
        default="0.15",
        help=softwrap(
            """
            The major/minor version of Apache Thrift that  you are using, such as `0.15`.

            Pants will only use Thrift binaries from `--thrift-search-paths` that have the
            expected version, and it will error if none are found.

            Do not include the patch version.
            """
        ),
    )

    def thrift_search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._thrift_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))
