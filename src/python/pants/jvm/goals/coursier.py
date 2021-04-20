# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
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
from pants.engine.target import Sources, Target, Targets
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile, MavenRequirements
from pants.jvm.target_types import JvmLockfileSources, MavenRequirementsField


class CoursierResolveSubsystem(GoalSubsystem):
    name = "coursier-resolve"
    help = "Generate a lockfile by resolving Maven dependencies."


class CoursierResolve(Goal):
    subsystem_cls = CoursierResolveSubsystem


@dataclass(frozen=True)
class CoursierGenerateLockfileRequest:
    """Regenerate a coursier_lockfile target's lockfile from its Maven requirements.

    This allows the user to manually regenerate their lockfile.  This is done for a few reasons: to
    generate the lockfile for the first time, to regenerate it because the input Maven requirements
    have changed, or to regenerate it to check if the resolve has changed (e.g. due to newer
    versions of dependencies being published).
    """

    target: Target


@dataclass(frozen=True)
class CoursierGenerateLockfileResult:
    digest: Digest


@rule
async def coursier_generate_lockfile(
    request: CoursierGenerateLockfileRequest,
) -> CoursierGenerateLockfileResult:
    resolved_lockfile = await Get(
        CoursierResolvedLockfile,
        MavenRequirements,
        MavenRequirements.create_from_maven_coordinates_fields(
            fields=(request.target[MavenRequirementsField],),
        ),
    )
    resolved_lockfile_json = resolved_lockfile.to_json()

    lockfile_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [request.target.get(Sources)],
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
