# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from typing import cast

from pants.engine.environment import Environment
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import OrderedSet


class ApacheThriftSubsystem(Subsystem):
    options_scope = "apache-thrift"
    help = "Apache Thrift IDL compiler (https://thrift.apache.org/)."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--thrift-search-paths",
            type=list,
            member_type=str,
            default=["<PATH>"],
            help=(
                "A list of paths to search for Thrift.\n\n"
                "Specify absolute paths to directories with the `thrift` binary, e.g. `/usr/bin`. "
                "Earlier entries will be searched first.\n\n"
                "The special string '<PATH>' will expand to the contents of the PATH env var."
            ),
        )
        register(
            "--expected-version",
            type=str,
            default="0.15",
            help=(
                "The major/minor version of Apache Thrift that  you are using, such as `0.15`.\n\n"
                "Pants will only use Thrift binaries from `--thrift-search-paths` that have the "
                "expected version, and it will error if none are found.\n\n"
                "Do not include the patch version."
            ),
        )

    @property
    def dependency_inference(self) -> bool:
        return cast(bool, self.options.dependency_inference)

    def thrift_search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.thrift_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))

    @property
    def expected_version(self) -> str:
        return cast(str, self.options.expected_version)
