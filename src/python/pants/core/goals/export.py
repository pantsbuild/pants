# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, cast

from pants.base.build_root import BuildRoot
from pants.core.goals.generate_lockfiles import (
    GenerateToolLockfileSentinel,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    UnrecognizedResolveNamesError,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import _warn_on_non_local_environments
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Effect, Get, MultiGet
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import FilteredTargets, Target
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import StrListOption
from pants.util.dirutil import safe_rmtree
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


class ExportError(Exception):
    pass


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ExportRequest:
    """A union for exportable data provided by a backend.

    Subclass and install a member of this type to export data.
    """

    targets: Sequence[Target]


@dataclass(frozen=True)
class PostProcessingCommand:
    """A command to run as a local process after an exported digest is materialized."""

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
        object.__setattr__(self, "argv", tuple(argv))
        object.__setattr__(self, "extra_env", FrozenDict(extra_env))


@dataclass(frozen=True)
class ExportResult:
    description: str
    # Materialize digests under this reldir.
    reldir: str
    # Materialize this digest.
    digest: Digest
    # Run these commands as local processes after the digest is materialized.
    post_processing_cmds: tuple[PostProcessingCommand, ...]
    # Set for the common special case of exporting a resolve, and names that resolve.
    # Set to None for other export results.
    resolve: str | None

    def __init__(
        self,
        description: str,
        reldir: str,
        *,
        digest: Digest = EMPTY_DIGEST,
        post_processing_cmds: Iterable[PostProcessingCommand] = tuple(),
        resolve: str | None = None,
    ):
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "reldir", reldir)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "post_processing_cmds", tuple(post_processing_cmds))
        object.__setattr__(self, "resolve", resolve)


class ExportResults(Collection[ExportResult]):
    pass


class ExportSubsystem(GoalSubsystem):
    name = "export"
    help = softwrap(
        """
        Export Pants data for use in other tools, such as IDEs.

        :::caution Exporting tools requires creating a custom lockfile for them
        Follow [the instructions for creating tool lockfiles](../../docs/python/overview/lockfiles#lockfiles-for-tools)
        :::
        """
    )

    # NB: Only options that are relevant across many/most backends and languages
    #  should be defined here.  Backend-specific options should be defined in that backend
    #  as plugin options on this subsystem.

    # Exporting resolves is a common use-case for `export`, often the primary one, so we
    # add affordances for it at the core goal level.
    resolve = StrListOption(
        default=[],
        help="Export the specified resolve(s). The export format is backend-specific, "
        "e.g., Python resolves are exported as virtualenvs.",
    )


class Export(Goal):
    subsystem_cls = ExportSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def export(
    console: Console,
    targets: FilteredTargets,
    workspace: Workspace,
    union_membership: UnionMembership,
    build_root: BuildRoot,
    dist_dir: DistDir,
    export_subsys: ExportSubsystem,
) -> Export:
    request_types = cast("Iterable[type[ExportRequest]]", union_membership.get(ExportRequest))
    requests = tuple(request_type(targets) for request_type in request_types)
    all_results = await MultiGet(Get(ExportResults, ExportRequest, request) for request in requests)
    flattened_results = [res for results in all_results for res in results]

    await _warn_on_non_local_environments(targets, "the `export` goal")

    prefixed_digests = await MultiGet(
        Get(Digest, AddPrefix(result.digest, result.reldir)) for result in flattened_results
    )
    output_dir = os.path.join(str(dist_dir.relpath), "export")
    for result in flattened_results:
        digest_root = os.path.join(build_root.path, output_dir, result.reldir)
        safe_rmtree(digest_root)
    merged_digest = await Get(Digest, MergeDigests(prefixed_digests))
    dist_digest = await Get(Digest, AddPrefix(merged_digest, output_dir))
    workspace.write_digest(dist_digest)
    environment = await Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"]))
    resolves_exported = set()
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
        if result.resolve:
            resolves_exported.add(result.resolve)
        console.print_stdout(f"Wrote {result.description} to {result_dir}")

    unexported_resolves = sorted((set(export_subsys.resolve) - resolves_exported))
    if unexported_resolves:
        all_known_user_resolve_names = await MultiGet(
            Get(KnownUserResolveNames, KnownUserResolveNamesRequest, request())
            for request in union_membership.get(KnownUserResolveNamesRequest)
        )
        all_valid_resolve_names = sorted(
            {
                *itertools.chain.from_iterable(kurn.names for kurn in all_known_user_resolve_names),
                *(
                    sentinel.resolve_name
                    for sentinel in union_membership.get(GenerateToolLockfileSentinel)
                ),
            }
        )
        raise UnrecognizedResolveNamesError(
            unexported_resolves,
            all_valid_resolve_names,
            description_of_origin="the option --export-resolve",
        )

    return Export(exit_code=0)


def rules():
    return collect_rules()
