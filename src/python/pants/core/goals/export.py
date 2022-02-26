# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Iterable, cast

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.environment import Environment, EnvironmentRequest
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
class ExportRequest:
    """A union for exportable data provided by a backend.

    Subclass and install a member of this type to export data.
    """

    targets: Targets


@dataclass(frozen=True)
class Symlink:
    """A symlink from link_rel_path pointing to source_path.

    source_path may be absolute, or relative to the repo root.

    link_rel_path is relative to the enclosing ExportResult's reldir, and will be
    absolutized when a location for that dir is chosen.
    """

    source_path: str
    link_rel_path: str


@frozen_after_init
@dataclass(unsafe_hash=True)
class ExportResult:
    description: str
    # Materialize digests and create symlinks under this reldir.
    reldir: str
    # Materialize this digest.
    digest: Digest
    # Create these symlinks. Symlinks are created after the digest is materialized,
    # so may reference files/dirs in the digest.
    # TODO: Remove this functionality entirely? We introduced symlinks as a too-clever way of
    #  linking from distdir into named caches. However that is risky, so we don't currently use it.
    symlinks: tuple[Symlink, ...]
    # Run these shell commands as local processes after the digest is materialized.
    # Note that each string element is an entire command to be parsed and interpreted by the shell.
    # Each command will be run with the following environment:
    #  PATH: The pants process's original PATH.
    #  DIGEST_ROOT: The location under the distdir in which the digest is materialized.
    post_processing_shell_cmds: tuple[str, ...]

    def __init__(
        self,
        description: str,
        reldir: str,
        *,
        digest: Digest = EMPTY_DIGEST,
        symlinks: Iterable[Symlink] = tuple(),
        post_processing_shell_cmds: Iterable[str] = tuple(),
    ):
        self.description = description
        self.reldir = reldir
        self.digest = digest
        self.symlinks = tuple(symlinks)
        self.post_processing_shell_cmds = tuple(post_processing_shell_cmds)


class ExportResults(Collection[ExportResult]):
    pass


class ExportSubsystem(GoalSubsystem):
    name = "export"
    help = "Export Pants data for use in other tools, such as IDEs."


class Export(Goal):
    subsystem_cls = ExportSubsystem


@goal_rule
async def export(
    console: Console,
    targets: Targets,
    workspace: Workspace,
    union_membership: UnionMembership,
    build_root: BuildRoot,
    dist_dir: DistDir,
) -> Export:
    request_types = cast("Iterable[type[ExportRequest]]", union_membership.get(ExportRequest))
    requests = tuple(request_type(targets) for request_type in request_types)
    all_results = await MultiGet(Get(ExportResults, ExportRequest, request) for request in requests)
    flattened_results = [res for results in all_results for res in results]

    prefixed_digests = await MultiGet(
        Get(Digest, AddPrefix(result.digest, result.reldir)) for result in flattened_results
    )
    output_dir = os.path.join(str(dist_dir.relpath), "export")
    merged_digest = await Get(Digest, MergeDigests(prefixed_digests))
    dist_digest = await Get(Digest, AddPrefix(merged_digest, output_dir))
    workspace.write_digest(dist_digest)
    environment = await Get(Environment, EnvironmentRequest(["PATH"]))
    for result in flattened_results:
        for symlink in result.symlinks:
            # Note that if symlink.source_path is an abspath, join returns it unchanged.
            source_abspath = os.path.join(build_root.path, symlink.source_path)
            link_abspath = os.path.abspath(
                os.path.join(output_dir, result.reldir, symlink.link_rel_path)
            )
            absolute_symlink(source_abspath, link_abspath)
        for cmd in result.post_processing_shell_cmds:
            # These are side-effecting, non-cacheable, and local-only, so we don't use Process.
            try:
                subprocess.check_output(
                    cmd,
                    stderr=subprocess.STDOUT,
                    shell=True,
                    env={
                        "PATH": environment.get("PATH", ""),
                        "DIGEST_ROOT": os.path.join(build_root.path, output_dir, result.reldir),
                    },
                )
            except subprocess.CalledProcessError as e:
                raise ExportError(
                    f"Post-processing command `{cmd}` failed with exit code "
                    f"{e.returncode}: {e.output}"
                )

        console.print_stdout(
            f"Wrote {result.description} to {os.path.join(output_dir, result.reldir)}"
        )
    return Export(exit_code=0)


def rules():
    return collect_rules()
