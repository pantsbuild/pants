# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.project_info.dependees import Dependees, DependeesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    InvalidTargetException,
    SourcesField,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    CoursierResolvedLockfile,
)
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactFieldSet,
    JvmArtifactGroupField,
    JvmArtifactVersionField,
    JvmLockfileSources,
    JvmRequirementsField,
)
from pants.util.logging import LogLevel


class CoursierResolveSubsystem(GoalSubsystem):
    name = "coursier-resolve"
    help = "Generate a lockfile by resolving JVM dependencies."


class CoursierResolve(Goal):
    subsystem_cls = CoursierResolveSubsystem


@dataclass(frozen=True)
class GatherArtifactRequirementsRequest:
    """Gather the coordinate requirements from a JarRequirementsField."""

    requirements: JvmRequirementsField


@rule(level=LogLevel.DEBUG)
async def gather_artifact_requirements(
    request: GatherArtifactRequirementsRequest,
) -> ArtifactRequirements:

    requirements_addresses = await Get(
        Addresses, UnparsedAddressInputs, request.requirements.to_unparsed_address_inputs()
    )
    requirements_targets = await Get(Targets, Addresses, requirements_addresses)

    return ArtifactRequirements(_coordinate_from_target(tgt) for tgt in requirements_targets)


def _coordinate_from_target(tgt: Target) -> Coordinate:
    group = tgt[JvmArtifactGroupField].value
    if not group:
        raise InvalidTargetException(
            f"The `group` field of {tgt.alias} target {tgt.address} must be set."
        )

    artifact = tgt[JvmArtifactArtifactField].value
    if not artifact:
        raise InvalidTargetException(
            f"The `artifact` field of {tgt.alias} target {tgt.address} must be set."
        )

    version = tgt[JvmArtifactVersionField].value
    if not version:
        raise InvalidTargetException(
            f"The `version` field of {tgt.alias} target {tgt.address} must be set."
        )

    return Coordinate(
        group=group,
        artifact=artifact,
        version=version,
    )


@dataclass(frozen=True)
class CoursierGenerateLockfileRequest:
    """Regenerate a coursier_lockfile target's lockfile from its JVM requirements.

    This request allows a user to manually regenerate their lockfile. This is done for a few reasons: to
    generate the lockfile for the first time, to regenerate it because the input JVM requirements
    have changed, or to regenerate it to check if the resolve has changed (e.g. due to newer
    versions of dependencies being published).

    target: The `coursier_lockfile` target to operate on
    """

    target: Target


@dataclass(frozen=True)
class CoursierGenerateLockfileResult:
    digest: Digest


@rule
async def coursier_generate_lockfile(
    request: CoursierGenerateLockfileRequest,
) -> CoursierGenerateLockfileResult:

    # This task finds all of the sources that depend on this lockfile, and then resolves
    # a lockfile that satisfies all of their `jvm_artifact` dependencies.

    # Find all targets that (directly or indirectly) depend on this lockfile
    dependees = await Get(
        Dependees,
        DependeesRequest(
            [request.target.address],
            transitive=True,
            include_roots=True,
        ),
    )

    # Find JVM artifacts in the dependency tree of the targets that depend on this lockfile.
    # These artifacts constitute the requirements that will be resolved for this lockfile.
    dependee_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(dependees))
    resolvable_dependencies = [
        tgt for tgt in dependee_targets.closure if JvmArtifactFieldSet.is_applicable(tgt)
    ]

    artifact_requirements = ArtifactRequirements(
        [_coordinate_from_target(tgt) for tgt in resolvable_dependencies]
    )

    resolved_lockfile = await Get(
        CoursierResolvedLockfile,
        ArtifactRequirements,
        artifact_requirements,
    )
    resolved_lockfile_json = resolved_lockfile.to_json()

    lockfile_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [request.target.get(SourcesField)],
            for_sources_types=[JvmLockfileSources],
            enable_codegen=False,
        ),
    )
    if not lockfile_sources.files:
        # The user defined the target and resolved it, but hasn't created a lockfile yet.
        # For convenience, create the initial lockfile for them in the default path.
        return CoursierGenerateLockfileResult(
            digest=await Get(
                Digest,
                CreateDigest(
                    (
                        FileContent(
                            path=os.path.join(
                                request.target.address.spec_path, "coursier_resolve.lockfile"
                            ),
                            content=resolved_lockfile_json,
                        ),
                    )
                ),
            )
        )

    # We know that there is at least one lockfile source, and also at most 1 because of
    # JvmLockfileSources.expected_num_files, so we can blindly grab its only source.
    source_lockfile_digest_contents = await Get(
        DigestContents, Digest, lockfile_sources.snapshot.digest
    )
    source_lockfile_content = source_lockfile_digest_contents[0]
    if resolved_lockfile_json != source_lockfile_content.content:
        # The generated lockfile differs from the existing one, so return the digest of the generated one.
        return CoursierGenerateLockfileResult(
            digest=await Get(
                Digest,
                CreateDigest(
                    (
                        FileContent(
                            path=source_lockfile_content.path, content=resolved_lockfile_json
                        ),
                    )
                ),
            )
        )
    # The generated lockfile didn't change, so return an empty digest.
    return CoursierGenerateLockfileResult(
        digest=EMPTY_DIGEST,
    )


@goal_rule
async def coursier_resolve_lockfiles(
    console: Console,
    targets: Targets,
    resolve_subsystem: CoursierResolveSubsystem,
    workspace: Workspace,
) -> CoursierResolve:
    jvm_lockfile_targets = Targets(
        target for target in targets if target.has_field(JvmLockfileSources)
    )
    results = await MultiGet(
        Get(CoursierGenerateLockfileResult, CoursierGenerateLockfileRequest(target=target))
        for target in jvm_lockfile_targets
    )
    # For performance reasons, avoid writing out files to the workspace that haven't changed.
    results_to_write = tuple(result for result in results if result.digest != EMPTY_DIGEST)
    if results_to_write:
        merged_digest = await Get(
            Digest, MergeDigests(result.digest for result in results_to_write)
        )
        workspace.write_digest(merged_digest)
        merged_digest_snapshot = await Get(Snapshot, Digest, merged_digest)
        for path in merged_digest_snapshot.files:
            console.print_stderr(f"Updated lockfile at: {path}")

    return CoursierResolve(exit_code=0)


def rules():
    return [*collect_rules()]
