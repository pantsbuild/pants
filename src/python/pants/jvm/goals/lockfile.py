# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping

from pants.core.goals.export import ExportError, ExportSubsystem, UserExport
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    GenerateLockfilesSubsystem,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
    WrappedGenerateLockfile,
)
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.jvm.resolve import coursier_fetch
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactResolveField, JvmResolveField
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


@rule
def determine_jvm_user_resolves(
    _: KnownJVMUserResolveNamesRequest, jvm_subsystem: JvmSubsystem
) -> KnownUserResolveNames:
    return KnownUserResolveNames(
        names=tuple(jvm_subsystem.resolves.keys()),
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
) -> UserGenerateLockfiles:
    resolve_to_artifacts: Mapping[str, OrderedSet[ArtifactRequirement]] = defaultdict(OrderedSet)
    for tgt in sorted(all_targets, key=lambda t: t.address):
        if not tgt.has_field(JvmArtifactResolveField):
            continue
        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        resolve = tgt[JvmResolveField].normalized_value(jvm_subsystem)
        resolve_to_artifacts[resolve].add(artifact)

    # Generate a JVM lockfile request for each requested resolve. This step also allows other backends to
    # validate the proposed set of artifact requirements for each resolve.
    jvm_lockfile_requests = await MultiGet(
        Get(
            GenerateJvmLockfile,
            _ValidateJvmArtifactsRequest(
                artifacts=ArtifactRequirements(resolve_to_artifacts.get(resolve, ())),
                resolve_name=resolve,
            ),
        )
        for resolve in requested
    )

    return UserGenerateLockfiles(jvm_lockfile_requests)


@rule
async def resolve2export(
    request: RequestedJVMUserResolveNames, export_subsys: ExportSubsystem
) -> UserExport:
    if request:
        raise ExportError(f"JVM backend does not support exporting. Received request {request}.")
    else:
        return UserExport(())


def rules():
    return (
        *collect_rules(),
        *coursier_fetch.rules(),
        UnionRule(GenerateLockfile, GenerateJvmLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownJVMUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedJVMUserResolveNames),
    )
