# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence, cast

from pants.base.build_root import BuildRoot
from pants.core.goals.generate_lockfiles import (
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    UnrecognizedResolveNamesError,
)
from pants.core.goals.resolves import ExportableTool, ExportMode
from pants.core.util_rules.distdir import DistDir
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    MergeDigests,
    SymlinkEntry,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.intrinsics import run_interactive_process
from pants.engine.process import InteractiveProcess
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import FilteredTargets, Target
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import StrListOption
from pants.util.dirutil import safe_mkdir, safe_rmtree
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
class ExportedBinary:
    """Binaries exposed by an export.

    These will be added under the "bin" folder. The `name` is the name that will be linked as in the
    `bin` folder. The `path_in_export` is the path within the exported digest to link to. These can
    be used to abstract details from the name of the tool and avoid the other files in the tool's
    digest.

    For example, "my-tool" might have a downloaded file of
    "my_tool/my_tool_linux_x86-64.bin" and a readme. We would use `ExportedBinary(name="my-tool",
    path_in_export=my_tool/my_tool_linux_x86-64.bin"`
    """

    name: str
    path_in_export: str


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
    exported_binaries: tuple[ExportedBinary, ...]

    def __init__(
        self,
        description: str,
        reldir: str,
        *,
        digest: Digest = EMPTY_DIGEST,
        post_processing_cmds: Iterable[PostProcessingCommand] = tuple(),
        resolve: str | None = None,
        exported_binaries: Iterable[ExportedBinary] = tuple(),
    ):
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "reldir", reldir)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "post_processing_cmds", tuple(post_processing_cmds))
        object.__setattr__(self, "resolve", resolve)
        object.__setattr__(self, "exported_binaries", tuple(exported_binaries))


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

    binaries = StrListOption(
        flag_name="--bin",  # `bin` is a python builtin
        default=[],
        help="Export the specified binaries. To select a binary, provide its subsystem scope name, as used for setting its options.",
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

    if not (export_subsys.resolve or export_subsys.options.bin):
        raise ExportError("Must specify at least one `--resolve` or `--bin` to export")
    if targets:
        raise ExportError("The `export` goal does not take target specs.")

    requests = tuple(request_type(targets) for request_type in request_types)
    all_results = await MultiGet(Get(ExportResults, ExportRequest, request) for request in requests)
    flattened_results = sorted(
        (res for results in all_results for res in results), key=lambda res: res.resolve or ""
    )  # sorting provides predictable resolution in conflicts

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
            ipr = await run_interactive_process(ip)
            if ipr.exit_code:
                raise ExportError(f"Failed to write {result.description} to {result_dir}")
        if result.resolve:
            resolves_exported.add(result.resolve)
        console.print_stdout(f"Wrote {result.description} to {result_dir}")

    exported_bins_by_exporting_resolve, link_requests = await link_exported_executables(
        build_root, output_dir, flattened_results
    )
    link_digest = await Get(Digest, CreateDigest, link_requests)
    workspace.write_digest(link_digest)

    exported_bin_warnings = warn_exported_bin_conflicts(exported_bins_by_exporting_resolve)
    for warning in exported_bin_warnings:
        console.print_stderr(warning)

    unexported_resolves = sorted(
        (set(export_subsys.resolve) | set(export_subsys.binaries)) - resolves_exported
    )
    if unexported_resolves:
        all_known_user_resolve_names = await MultiGet(
            Get(KnownUserResolveNames, KnownUserResolveNamesRequest, request())
            for request in union_membership.get(KnownUserResolveNamesRequest)
        )
        all_known_bin_names = [
            e.options_scope
            for e in union_membership.get(ExportableTool)
            if e.export_mode == ExportMode.binary
        ]
        all_valid_resolve_names = sorted(
            {
                *itertools.chain.from_iterable(kurn.names for kurn in all_known_user_resolve_names),
            }
        )
        raise UnrecognizedResolveNamesError(
            unexported_resolves,
            all_valid_resolve_names,
            all_known_bin_names,
            description_of_origin="the options --export-resolve and/or --export-bin",
        )

    return Export(exit_code=0)


async def link_exported_executables(
    build_root: BuildRoot,
    output_dir: str,
    export_results: list[ExportResult],
) -> tuple[dict[str, list[str]], CreateDigest]:
    """Link the exported executables to the `bin` dir.

    Multiple resolves might export the same executable. This will export the first one only but
    track the collision.
    """
    safe_mkdir(Path(output_dir, "bin"))

    exported_bins_by_exporting_resolve: dict[str, list[str]] = defaultdict(list)
    link_requests = []
    for result in export_results:
        for exported_bin in result.exported_binaries:
            exported_bins_by_exporting_resolve[exported_bin.name].append(
                result.resolve or result.description
            )
            if len(exported_bins_by_exporting_resolve[exported_bin.name]) > 1:
                continue

            path = Path(output_dir, "bin", exported_bin.name)
            target = Path(build_root.path, output_dir, result.reldir, exported_bin.path_in_export)
            link_requests.append(SymlinkEntry(path.as_posix(), target.as_posix()))

    return exported_bins_by_exporting_resolve, CreateDigest(link_requests)


def warn_exported_bin_conflicts(exported_bins: dict[str, list[str]]) -> list[str]:
    """Check that no bin was exported from multiple resolves."""
    messages = []

    for exported_bin_name, resolves in exported_bins.items():
        if len(resolves) > 1:
            msg = f"Exporting binary `{exported_bin_name}` had conflicts. "
            succeeded_resolve, other_resolves = resolves[0], resolves[1:]
            msg += (
                f"The resolve {succeeded_resolve} was exported, but it conflicted with "
                + ", ".join(other_resolves)
            )
            messages.append(msg)

    return messages


def rules():
    return collect_rules()
