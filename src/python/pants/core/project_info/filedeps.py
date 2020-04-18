# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import PurePath
from typing import Iterable

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    Sources,
    Target,
    Targets,
    TransitiveTargets,
)


class FiledepsOptions(LineOriented, GoalSubsystem):
    """List all source and BUILD files a target depends on."""

    name = "filedeps2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--absolute",
            type=bool,
            default=True,
            help=(
                "If True, output with absolute path; else, output with path relative to the "
                "build root."
            ),
        )
        register(
            "--globs",
            type=bool,
            default=False,
            help=(
                "Instead of outputting filenames, output the original globs used in the BUILD "
                "file. This will not include exclude globs (i.e. globs that start with `!`)."
            ),
        )
        register(
            "--transitive",
            type=bool,
            default=False,
            help="If True, include the files used by dependencies in the output.",
        )


class Filedeps(Goal):
    subsystem_cls = FiledepsOptions


@goal_rule
async def file_deps(
    console: Console, options: FiledepsOptions, build_root: BuildRoot, addresses: Addresses,
) -> Filedeps:
    targets: Iterable[Target]
    if options.values.transitive:
        transitive_targets = await Get[TransitiveTargets](Addresses, addresses)
        targets = transitive_targets.closure
    else:
        targets = await Get[Targets](Addresses, addresses)

    build_file_addresses = await MultiGet(
        Get[BuildFileAddress](Address, tgt.address) for tgt in targets
    )
    unique_rel_paths = {bfa.rel_path for bfa in build_file_addresses}

    if options.values.globs:
        unique_rel_paths.update(
            itertools.chain.from_iterable(tgt.get(Sources).filespec["globs"] for tgt in targets)
        )
    else:
        all_hydrated_sources = await MultiGet(
            Get[HydratedSources](HydrateSourcesRequest, tgt.get(Sources).request) for tgt in targets
        )
        unique_rel_paths.update(
            itertools.chain.from_iterable(
                hydrated_sources.snapshot.files for hydrated_sources in all_hydrated_sources
            )
        )

    with options.line_oriented(console) as print_stdout:
        for rel_path in sorted(unique_rel_paths):
            final_path = (
                PurePath(build_root.path, rel_path).as_posix()
                if options.values.absolute
                else rel_path
            )
            print_stdout(final_path)

    return Filedeps(exit_code=0)


def rules():
    return [file_deps]
