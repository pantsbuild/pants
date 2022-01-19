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
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class JvmLockfileRequest(LockfileRequest):
    artifacts: ArtifactRequirements


@frozen_after_init
@dataclass(unsafe_hash=True)
class JvmLockfileRequestFromTool:
    artifact_inputs: FrozenOrderedSet[str]
    options_scope: str
    lockfile_dest: str

    def __init__(self, tool: JvmToolBase) -> None:
        # Note that `JvmToolBase` is not hashable, so we extract the relevant information eagerly.
        self.artifact_inputs = FrozenOrderedSet(tool.artifact_inputs)
        self.options_scope = tool.options_scope
        self.lockfile_dest = tool.lockfile


@rule
async def setup_lockfile_request_from_tool(
    request: JvmLockfileRequestFromTool,
) -> JvmLockfileRequest:
    artifacts = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(
            request.artifact_inputs,
            f"[{request.options_scope}].artifacts",
        ),
    )
    return JvmLockfileRequest(
        artifacts=artifacts,
        resolve_name=request.options_scope,
        lockfile_dest=request.lockfile_dest,
    )


@rule
def wrap_python_lockfile_request(request: JvmLockfileRequest) -> WrappedLockfileRequest:
    return WrappedLockfileRequest(request)


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: JvmLockfileRequest,
) -> Lockfile:
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, request.artifacts)

    resolved_lockfile_contents = resolved_lockfile.to_serialized()
    metadata = JVMLockfileMetadata.new(request.artifacts)
    resolved_lockfile_contents = metadata.add_header_to_lockfile(
        resolved_lockfile_contents, regenerate_command="./pants generate-lockfiles"
    )

    lockfile_digest = await Get(
        Digest,
        CreateDigest([FileContent(request.lockfile_dest, resolved_lockfile.to_serialized())]),
    )
    return Lockfile(lockfile_digest, request.resolve_name, request.lockfile_dest)


@rule
async def load_jvm_lockfile(
    request: JvmLockfileRequest,
) -> CoursierResolvedLockfile:
    """Loads an existing lockfile from disk."""
    if not request.artifacts:
        return CoursierResolvedLockfile(entries=())

    lockfile_snapshot = await Get(Snapshot, PathGlobs([request.lockfile_dest]))
    if not lockfile_snapshot.files:
        raise ValueError(
            f"JVM resolve `{request.resolve_name}` does not have a lockfile generated. "
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
