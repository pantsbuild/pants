# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, cast

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.dirutil import absolute_symlink
from pants.util.meta import frozen_after_init


class ExportError(Exception):
    pass


@union
@dataclass(frozen=True)
class ExportableDataRequest:
    """A union for exportable data provided by a backend.

    Subclass and install a member of this type to export data.
    """

    targets: Targets


@dataclass(frozen=True)
class Symlink:
    """A symlink from link_rel_path pointing to source_path.

    source_path may be absolute, or relative to the repo root.

    link_rel_path is relative to the enclosing ExportableData's reldir, and will be
    absolutized when a location for that dir is chosen.
    """

    source_path: str
    link_rel_path: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class ExportableData:
    description: str
    # Materialize digests and create symlinks under this reldir.
    reldir: str
    # Materialize this digest.
    digest: Digest
    # Create these symlinks. Symlinks are created after the digest is materialized,
    # so may reference files/dirs in the digest.
    symlinks: tuple[Symlink, ...]

    def __init__(
        self,
        description: str,
        reldir: str,
        *,
        digest: Digest = EMPTY_DIGEST,
        symlinks: Iterable[Symlink] = tuple(),
    ):
        self.description = description
        self.reldir = reldir
        self.digest = digest
        self.symlinks = tuple(symlinks)


class ExportSubsystem(GoalSubsystem):
    name = "export"
    help = "Export Pants data for use in other tools, such as IDEs."


class Export(Goal):
    subsystem_cls = ExportSubsystem


@goal_rule
async def export(
    console: Console,
    targets: Targets,
    export_subsystem: ExportSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
    build_root: BuildRoot,
    dist_dir: DistDir,
) -> Export:
    request_types = cast(
        "Iterable[type[ExportableDataRequest]]", union_membership.get(ExportableDataRequest)
    )
    requests = tuple(request_type(targets) for request_type in request_types)
    exportables = await MultiGet(
        Get(ExportableData, ExportableDataRequest, request) for request in requests
    )
    prefixed_digests = await MultiGet(
        Get(Digest, AddPrefix(exp.digest, exp.reldir)) for exp in exportables
    )
    output_dir = os.path.join(str(dist_dir.relpath), "export")
    merged_digest = await Get(Digest, MergeDigests(prefixed_digests))
    dist_digest = await Get(Digest, AddPrefix(merged_digest, output_dir))
    workspace.write_digest(dist_digest)
    for exp in exportables:
        for symlink in exp.symlinks:
            # Note that if symlink.source_path is an abspath, join returns it unchanged.
            source_abspath = os.path.join(build_root.path, symlink.source_path)
            link_abspath = os.path.abspath(
                os.path.join(output_dir, exp.reldir, symlink.link_rel_path)
            )
            absolute_symlink(source_abspath, link_abspath)
        console.print_stdout(f"Wrote {exp.description} to {os.path.join(output_dir, exp.reldir)}")
    return Export(exit_code=0)


def rules():
    return collect_rules()
