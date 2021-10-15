# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import PurePath
from typing import Iterable, cast

from pants.base.build_root import BuildRoot
from pants.engine.addresses import Address, Addresses, BuildFileAddress
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)


class FiledepsSubsystem(LineOriented, GoalSubsystem):
    name = "filedeps"
    help = "List all source and BUILD files a target depends on."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--absolute",
            type=bool,
            default=False,
            help=(
                "If True, output with absolute path. If unspecified, output with path relative to "
                "the build root."
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
            help=(
                "If True, list files from all dependencies, including transitive dependencies. If "
                "unspecified, only list files from the target."
            ),
        )

    @property
    def absolute(self) -> bool:
        return cast(bool, self.options.absolute)

    @property
    def globs(self) -> bool:
        return cast(bool, self.options.globs)

    @property
    def transitive(self) -> bool:
        return cast(bool, self.options.transitive)


class Filedeps(Goal):
    subsystem_cls = FiledepsSubsystem


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
            TransitiveTargets, TransitiveTargetsRequest(addresses, include_special_cased_deps=True)
        )
        targets = transitive_targets.closure
    else:
        # NB: We must preserve target generators, not replace with their generated targets.
        targets = await Get(UnexpandedTargets, Addresses, addresses)

    build_file_addresses = await MultiGet(
        Get(BuildFileAddress, Address, tgt.address) for tgt in targets
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
