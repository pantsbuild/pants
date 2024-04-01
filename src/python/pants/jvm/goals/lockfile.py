# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.core.goals.generate_lockfiles import (
    DEFAULT_TOOL_LOCKFILE,
    GenerateLockfile,
    GenerateLockfileResult,
    GenerateLockfilesSubsystem,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
    WrappedGenerateLockfile,
)
from pants.core.goals.resolves import ExportableTool
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.jvm.resolve import coursier_fetch
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    GatherJvmCoordinatesRequest,
)
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactResolveField, JvmResolveField
from pants.option.subsystem import _construct_subsystem
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class GenerateJvmLockfile(GenerateLockfile):
    artifacts: ArtifactRequirements


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ValidateJvmArtifactsForResolveRequest:
    """Hook for backends to validate the artifact requirements requested for a resolve.

    The main user is the Scala backend which will ensure scala-library is present in the resolve.
    """

    artifacts: ArtifactRequirements
    resolve_name: str


@dataclass(frozen=True)
class ValidateJvmArtifactsForResolveResult:
    """Sentinel type that represents that a backend is satisfied with the artifacts for a JVM
    resolve."""


@rule
def wrap_jvm_lockfile_request(request: GenerateJvmLockfile) -> WrappedGenerateLockfile:
    return WrappedGenerateLockfile(request)


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: GenerateJvmLockfile,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
) -> GenerateLockfileResult:
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, request.artifacts)
    regenerate_command = (
        generate_lockfiles_subsystem.custom_command or f"{bin_name()} generate-lockfiles"
    )

    resolved_lockfile_contents = resolved_lockfile.to_serialized()
    metadata = JVMLockfileMetadata.new(request.artifacts)
    resolved_lockfile_contents = metadata.add_header_to_lockfile(
        resolved_lockfile_contents,
        regenerate_command=regenerate_command,
        delimeter="#",
    )

    lockfile_digest = await Get(
        Digest,
        CreateDigest([FileContent(request.lockfile_dest, resolved_lockfile_contents)]),
    )
    return GenerateLockfileResult(lockfile_digest, request.resolve_name, request.lockfile_dest)


class RequestedJVMUserResolveNames(RequestedUserResolveNames):
    pass


class KnownJVMUserResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


def jvm_exportable_tools(union_membership: UnionMembership) -> dict[str, type[JvmToolBase]]:
    exportable_tools = union_membership.get(ExportableTool)
    names_of_jvm_tools: dict[str, type[JvmToolBase]] = {
        e.options_scope: e for e in exportable_tools if issubclass(e, JvmToolBase)  # type: ignore  # mypy isn't narrowing with `issubclass`
    }
    return names_of_jvm_tools


@rule
def determine_jvm_user_resolves(
    _: KnownJVMUserResolveNamesRequest,
    jvm_subsystem: JvmSubsystem,
    union_membership: UnionMembership,
) -> KnownUserResolveNames:
    jvm_tool_resolves = jvm_exportable_tools(union_membership)
    names = (*jvm_subsystem.resolves.keys(), *jvm_tool_resolves.keys())
    return KnownUserResolveNames(
        names=names,
        option_name=f"[{jvm_subsystem.options_scope}].resolves",
        requested_resolve_names_cls=RequestedJVMUserResolveNames,
    )


@dataclass(frozen=True)
class _ValidateJvmArtifactsRequest:
    artifacts: ArtifactRequirements
    resolve_name: str


@rule
async def validate_jvm_artifacts_for_resolve(
    request: _ValidateJvmArtifactsRequest,
    union_membership: UnionMembership,
    jvm_subsystem: JvmSubsystem,
) -> GenerateJvmLockfile:
    impls = union_membership.get(ValidateJvmArtifactsForResolveRequest)
    for impl in impls:
        validate_request = impl(artifacts=request.artifacts, resolve_name=request.resolve_name)
        _ = await Get(  # noqa: PNT30: requires triage
            ValidateJvmArtifactsForResolveResult,
            ValidateJvmArtifactsForResolveRequest,
            validate_request,
        )

    return GenerateJvmLockfile(
        artifacts=request.artifacts,
        resolve_name=request.resolve_name,
        lockfile_dest=jvm_subsystem.resolves[request.resolve_name],
        diff=False,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedJVMUserResolveNames,
    all_targets: AllTargets,
    jvm_subsystem: JvmSubsystem,
    union_membership: UnionMembership,
) -> UserGenerateLockfiles:
    resolve_to_artifacts: Mapping[str, OrderedSet[ArtifactRequirement]] = defaultdict(OrderedSet)
    for tgt in sorted(all_targets, key=lambda t: t.address):
        if not tgt.has_field(JvmArtifactResolveField):
            continue
        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        resolve = tgt[JvmResolveField].normalized_value(jvm_subsystem)
        resolve_to_artifacts[resolve].add(artifact)

    tools = jvm_exportable_tools(union_membership)

    # Generate a JVM lockfile request for each requested resolve. This step also allows other backends to
    # validate the proposed set of artifact requirements for each resolve.
    gets = []
    for resolve in requested:
        if resolve in resolve_to_artifacts:
            gets.append(
                Get(
                    GenerateJvmLockfile,
                    _ValidateJvmArtifactsRequest(
                        artifacts=ArtifactRequirements(resolve_to_artifacts.get(resolve, ())),
                        resolve_name=resolve,
                    ),
                )
            )
        elif resolve in tools:
            tool_cls: type[JvmToolBase] = tools[resolve]
            tool = await _construct_subsystem(tool_cls)

            gets.append(
                Get(
                    GenerateJvmLockfile,
                    GenerateJvmLockfileFromTool,
                    GenerateJvmLockfileFromTool.create(tool),
                )
            )

    jvm_lockfile_requests = await MultiGet(*gets)

    return UserGenerateLockfiles(jvm_lockfile_requests)


@rule
async def setup_lockfile_request_from_tool(
    request: GenerateJvmLockfileFromTool,
) -> GenerateJvmLockfile:
    artifacts = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(request.artifact_inputs, request.artifact_option_name),
    )
    return GenerateJvmLockfile(
        artifacts=artifacts,
        resolve_name=request.resolve_name,
        lockfile_dest=(
            request.write_lockfile_dest
            if request.read_lockfile_dest != DEFAULT_TOOL_LOCKFILE
            else DEFAULT_TOOL_LOCKFILE
        ),
        diff=False,
    )


def rules():
    return (
        *collect_rules(),
        *coursier_fetch.rules(),
        UnionRule(GenerateLockfile, GenerateJvmLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownJVMUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedJVMUserResolveNames),
    )
