# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import PurePath
from typing import Iterable

from pants.base.build_root import BuildRoot
from pants.build_graph.address import BuildFileAddressRequest
from pants.engine.addresses import Addresses, BuildFileAddress
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import (
    AlwaysTraverseDeps,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)
from pants.option.option_types import BoolOption
from pants.util.strutil import softwrap


class FiledepsSubsystem(LineOriented, GoalSubsystem):
    name = "filedeps"
    help = "List all source and BUILD files a target depends on."

    absolute = BoolOption(
        default=False,
        help=softwrap(
            """
            If True, output with absolute path. If unspecified, output with path relative to
            the build root.
            """
        ),
    )
    globs = BoolOption(
        default=False,
        help=softwrap(
            """
            Instead of outputting filenames, output the original globs used in the BUILD
            file. This will not include exclude globs (i.e. globs that start with `!`).
            """
        ),
    )
    transitive = BoolOption(
        default=False,
        help=softwrap(
            """
            If True, list files from all dependencies, including transitive dependencies. If
            unspecified, only list files from the target.
            """
        ),
    )


class Filedeps(Goal):
    subsystem_cls = FiledepsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def file_deps(
    console: Console,
    filedeps_subsystem: FiledepsSubsystem,
    build_root: BuildRoot,
    addresses: Addresses,
) -> Filedeps:
    targets: Iterable[Target]
    if filedeps_subsystem.transitive:
        transitive_targets = await Get(
            TransitiveTargets,
            TransitiveTargetsRequest(
                addresses, should_traverse_deps_predicate=AlwaysTraverseDeps()
            ),
        )
        targets = transitive_targets.closure
    else:
        # NB: We must preserve target generators, not replace with their generated targets.
        targets = await Get(UnexpandedTargets, Addresses, addresses)

    build_file_addresses = await MultiGet(
        Get(
            BuildFileAddress,
            BuildFileAddressRequest(tgt.address, description_of_origin="CLI arguments"),
        )
        for tgt in targets
    )
    unique_rel_paths = {bfa.rel_path for bfa in build_file_addresses}

    if filedeps_subsystem.globs:
        unique_rel_paths.update(
            itertools.chain.from_iterable(
                tgt.get(SourcesField).filespec["includes"] for tgt in targets
            )
        )
    else:
        all_hydrated_sources = await MultiGet(
            Get(HydratedSources, HydrateSourcesRequest(tgt.get(SourcesField))) for tgt in targets
        )
        unique_rel_paths.update(
            itertools.chain.from_iterable(
                hydrated_sources.snapshot.files for hydrated_sources in all_hydrated_sources
            )
        )

    with filedeps_subsystem.line_oriented(console) as print_stdout:
        for rel_path in sorted(unique_rel_paths):
            final_path = (
                PurePath(build_root.path, rel_path).as_posix()
                if filedeps_subsystem.absolute
                else rel_path
            )
            print_stdout(final_path)

    return Filedeps(exit_code=0)


def rules():
    return collect_rules()
