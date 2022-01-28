# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
    WrappedGenerateLockfile,
)
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionRule
from pants.jvm.resolve import coursier_fetch
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactCompatibleResolvesField
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GenerateJvmLockfile(GenerateLockfile):
    artifacts: ArtifactRequirements


@rule
def wrap_jvm_lockfile_request(request: GenerateJvmLockfile) -> WrappedGenerateLockfile:
    return WrappedGenerateLockfile(request)


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: GenerateJvmLockfile,
) -> GenerateLockfileResult:
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, request.artifacts)

    resolved_lockfile_contents = resolved_lockfile.to_serialized()
    metadata = JVMLockfileMetadata.new(request.artifacts)
    resolved_lockfile_contents = metadata.add_header_to_lockfile(
        resolved_lockfile_contents, regenerate_command="./pants generate-lockfiles"
    )

    lockfile_digest = await Get(
        Digest,
        CreateDigest([FileContent(request.lockfile_dest, resolved_lockfile_contents)]),
    )
    return GenerateLockfileResult(lockfile_digest, request.resolve_name, request.lockfile_dest)


class RequestedJVMserResolveNames(RequestedUserResolveNames):
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
        requested_resolve_names_cls=RequestedJVMserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedJVMserResolveNames, all_targets: AllTargets, jvm_subsystem: JvmSubsystem
) -> UserGenerateLockfiles:
    resolve_to_artifacts = defaultdict(set)
    for tgt in all_targets:
        if not tgt.has_field(JvmArtifactCompatibleResolvesField):
            continue
        artifact = ArtifactRequirement.from_jvm_artifact_target(tgt)
        for resolve in jvm_subsystem.resolves_for_target(tgt):
            resolve_to_artifacts[resolve].add(artifact)

    return UserGenerateLockfiles(
        GenerateJvmLockfile(
            # Note that it's legal to have a resolve with no artifacts.
            artifacts=ArtifactRequirements(sorted(resolve_to_artifacts.get(resolve, ()))),
            resolve_name=resolve,
            lockfile_dest=jvm_subsystem.resolves[resolve],
        )
        for resolve in requested
    )


def rules():
    return (
        *collect_rules(),
        *coursier_fetch.rules(),
        UnionRule(GenerateLockfile, GenerateJvmLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownJVMUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedJVMserResolveNames),
    )
