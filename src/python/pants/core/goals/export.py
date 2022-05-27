# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, cast

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Effect, Get, MultiGet
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import FilteredTargets, Target
from pants.engine.unions import UnionMembership, union
from pants.util.dirutil import safe_rmtree
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


class ExportError(Exception):
    pass


@union
@dataclass(frozen=True)
class ExportRequest:
    """A union for exportable data provided by a backend.

    Subclass and install a member of this type to export data.
    """

    targets: Sequence[Target]


@frozen_after_init
@dataclass(unsafe_hash=True)
class PostProcessingCommand:
    """A command to run as a local processe after an exported digest is materialized."""

    # Values in the argv tuple can contain the format specifier "{digest_root}", which will be
    # substituted with the (absolute) path to the location under distdir in which the
    # digest is materialized.
    argv: tuple[str, ...]
    # The command will be run with an environment consisting of just PATH, set to the Pants
    # process's own PATH env var, plus these extra env vars.
    extra_env: FrozenDict[str, str]

    def __init__(
        self,
        argv: Iterable[str],
        extra_env: Mapping[str, str] = FrozenDict(),
    ):
        self.argv = tuple(argv)
        self.extra_env = FrozenDict(extra_env)


@frozen_after_init
@dataclass(unsafe_hash=True)
class ExportResult:
    description: str
    # Materialize digests under this reldir.
    reldir: str
    # Materialize this digest.
    digest: Digest
    # Run these commands as local processes after the digest is materialized.
    # Values in each args string tuple can contain the format specifier "{digest_root}", which
    # will be substituted with the (absolute) path to the location under distdir in which the
    # digest is materialized.
    # Each command will be run with an environment consistent of just PATH, set to the Pants
    # process's own PATH env var.
    post_processing_cmds: tuple[PostProcessingCommand, ...]

    def __init__(
        self,
        description: str,
        reldir: str,
        *,
        digest: Digest = EMPTY_DIGEST,
        post_processing_cmds: Iterable[PostProcessingCommand] = tuple(),
    ):
        self.description = description
        self.reldir = reldir
        self.digest = digest
        self.post_processing_cmds = tuple(post_processing_cmds)


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
    targets: FilteredTargets,
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
    safe_rmtree(output_dir)
    merged_digest = await Get(Digest, MergeDigests(prefixed_digests))
    dist_digest = await Get(Digest, AddPrefix(merged_digest, output_dir))
    workspace.write_digest(dist_digest)
    environment = await Get(Environment, EnvironmentRequest(["PATH"]))
    for result in flattened_results:
        result_dir = os.path.join(output_dir, result.reldir)
        digest_root = os.path.join(build_root.path, result_dir)
        for cmd in result.post_processing_cmds:
            argv = tuple(arg.format(digest_root=digest_root) for arg in cmd.argv)
            ip = InteractiveProcess(
                argv=argv,
                env={"PATH": environment.get("PATH", ""), **cmd.extra_env},
                run_in_workspace=True,
            )
            ipr = await Effect(InteractiveProcessResult, InteractiveProcess, ip)
            if ipr.exit_code:
                raise ExportError(f"Failed to write {result.description} to {result_dir}")

        console.print_stdout(f"Wrote {result.description} to {result_dir}")
    return Export(exit_code=0)


def rules():
    return collect_rules()
