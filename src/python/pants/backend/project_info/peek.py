# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from enum import Enum
from typing import Iterable, cast

from pants.backend.project_info.depgraph import DependencyGraph, DependencyGraphRequest
from pants.engine.addresses import Address, Addresses, BuildFileAddress
from pants.engine.console import Console
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import UnexpandedTargets


# TODO: Delete this in 2.9.0.dev0.
class OutputOptions(Enum):
    RAW = "raw"
    JSON = "json"


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display detailed target information in JSON form."""

    name = "peek"
    help = "Display BUILD target info"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output",
            type=OutputOptions,
            default=OutputOptions.JSON,
            removal_version="2.9.0.dev0",
            removal_hint="Output will always be JSON. If you need the raw BUILD file contents, "
            "look at it directly!",
            help=(
                "Which output style peek should use: `json` will show each target as a seperate "
                "entry, whereas `raw` will simply show the original non-normalized BUILD files."
            ),
        )
        register(
            "--exclude-defaults",
            type=bool,
            default=False,
            help="Whether to leave off values that match the target-defined default values.",
        )

    # TODO: Delete this in 2.9.0.dev0.
    @property
    def output_type(self) -> OutputOptions:
        """Get the output type from options.

        Must be renamed here because `output` conflicts with `Outputting` class.
        """
        return cast(OutputOptions, self.options.output)

    @property
    def exclude_defaults(self) -> bool:
        return cast(bool, self.options.exclude_defaults)


class Peek(Goal):
    subsystem_cls = PeekSubsystem


# TODO: Delete this in 2.9.0.dev0.
def _render_raw(fcs: Iterable[FileContent]) -> str:
    sorted_fcs = sorted(fcs, key=lambda fc: fc.path)
    rendereds = map(_render_raw_build_file, sorted_fcs)
    return os.linesep.join(rendereds)


# TODO: Delete this in 2.9.0.dev0.
def _render_raw_build_file(fc: FileContent, encoding: str = "utf-8") -> str:
    dashes = "-" * len(fc.path)
    content = fc.content.decode(encoding)
    parts = [dashes, fc.path, dashes, content]
    if not content.endswith(os.linesep):
        parts.append("")
    return os.linesep.join(parts)


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    targets: UnexpandedTargets,
) -> Peek:
    # TODO: Delete this entire conditional in 2.9.0.dev0.
    if subsys.output_type == OutputOptions.RAW:
        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, t.address) for t in targets
        )
        build_file_paths = {a.rel_path for a in build_file_addresses}
        digest_contents = await Get(DigestContents, PathGlobs(build_file_paths))
        with subsys.output(console) as write_stdout:
            write_stdout(_render_raw(digest_contents))
        return Peek(exit_code=0)

    depgraph = await Get(
        DependencyGraph,
        DependencyGraphRequest(
            Addresses([tgt.address for tgt in targets]),
            transitive=False,
            exclude_defaults=subsys.exclude_defaults,
        ),
    )
    with subsys.output(console) as write_stdout:
        write_stdout(depgraph.to_dependencies_json())
    return Peek(exit_code=0)


def rules():
    return collect_rules()
