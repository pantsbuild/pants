# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Iterable, cast

from pants.engine.addresses import Address, Addresses, BuildFileAddress
from pants.engine.console import Console
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Target, Targets


class OutputOptions(Enum):
    RAW = "raw"
    JSON = "json"


class PeekSubsystem(GoalSubsystem):
    """Display BUILD file info to the console.

    In its most basic form, `peek` just prints the contents of a BUILD file. It can also display
    multiple BUILD files, or render normalized target metadata as JSON for consumption by other
    programs.
    """

    name = "peek"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output",
            type=OutputOptions,
            default=OutputOptions.RAW,
            help="which output style peek should use",
        )

    @property
    def output(self) -> OutputOptions:
        return cast(OutputOptions, self.options.output)


class Peek(Goal):
    subsystem_cls = PeekSubsystem


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    addresses: Addresses,
) -> Peek:
    # TODO: better options for target selection (globs, transitive, etc)?
    targets: Iterable[Target]
    targets = await Get(Targets, Addresses, addresses)
    build_file_addresses = await MultiGet(
        Get(BuildFileAddress, Address, t.address) for t in targets
    )
    build_file_paths = {a.rel_path for a in build_file_addresses}
    digests = await Get(DigestContents, PathGlobs(build_file_paths))

    # TODO: programmatically determine correct encoding
    encoding = "utf-8"
    if len(digests) == 1:
        content = digests[0].content.decode(encoding)
        console.print_stdout(content)
    else:
        raise NotImplementedError("do it")

    return Peek(exit_code=0)


def rules():
    return collect_rules()
