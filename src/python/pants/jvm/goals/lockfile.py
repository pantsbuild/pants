# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.generate_lockfiles import (
    GenerateLockfilesSubsystem,
    Lockfile,
    LockfileRequest,
    WrappedLockfileRequest,
)
from pants.engine.fs import CreateDigest, Digest, FileContent, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.resolve import coursier_fetch, jvm_tool
from pants.jvm.resolve.common import ArtifactRequirements
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile
from pants.jvm.resolve.jvm_tool import GatherJvmCoordinatesRequest, JvmToolBase
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class JvmLockfileRequest(LockfileRequest):
    artifact_inputs: FrozenOrderedSet[str]

    @classmethod
    def from_tool(cls, tool: JvmToolBase) -> JvmLockfileRequest:
        return cls(
            artifact_inputs=FrozenOrderedSet(tool.artifact_inputs),
            resolve_name=tool.options_scope,
            lockfile_dest=tool.lockfile,
        )


@rule
def wrap_python_lockfile_request(request: JvmLockfileRequest) -> WrappedLockfileRequest:
    return WrappedLockfileRequest(request)


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: JvmLockfileRequest,
) -> Lockfile:
    requirements = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(request.artifact_inputs, f"[{request.resolve_name}].artifacts"),
    )
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, requirements)
    
    resolved_lockfile_contents = resolved_lockfile.to_serialized()
    metadata = JVMLockfileMetadata.new(requirements)
    resolved_lockfile_contents = metadata.add_header_to_lockfile(resolved_lockfile_contents, regenerate_command="./pants generate-lockfiles")

    lockfile_digest = await Get(
        Digest,
        CreateDigest([FileContent(request.lockfile_dest, resolved_lockfile_contents)]),
    )
    return Lockfile(lockfile_digest, request.resolve_name, request.lockfile_dest)


@rule
async def load_jvm_lockfile(
    request: JvmLockfileRequest,
) -> CoursierResolvedLockfile:
    """Loads an existing lockfile from disk."""
    if not request.artifact_inputs:
        return CoursierResolvedLockfile(entries=())

    lockfile_snapshot = await Get(Snapshot, PathGlobs([request.lockfile_dest]))
    if not lockfile_snapshot.files:
        raise ValueError(
            f"JVM tool `{request.resolve_name}` does not have a lockfile generated. "
            f"Run `{GenerateLockfilesSubsystem.name} --resolve={request.resolve_name} to "
            "generate it."
        )

    return await Get(
        CoursierResolvedLockfile,
        CoursierResolveKey(
            name=request.resolve_name, path=request.lockfile_dest, digest=lockfile_snapshot.digest
        ),
    )


def rules():
    return (
        *collect_rules(),
        *coursier_fetch.rules(),
        *jvm_tool.rules(),
        UnionRule(LockfileRequest, JvmLockfileRequest),
    )
