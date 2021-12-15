# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from pants.engine.addresses import Address
from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import AllTargets, TransitiveTargets, TransitiveTargetsRequest
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirement,
    ArtifactRequirements,
    CoursierError,
    CoursierResolvedLockfile,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactFieldSet, JvmCompatibleResolvesField, JvmResolveField
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


class CoursierResolveSubsystem(GoalSubsystem):
    name = "coursier-resolve"
    help = "Generate a lockfile by resolving JVM dependencies."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--names",
            type=list,
            help=(
                "A list of resolve names to resolve.\n\n"
                "Each name must be defined as a resolve in `[jvm].resolves`.\n\n"
                "If not provided, resolve all known resolves."
            ),
        )


class CoursierResolve(Goal):
    subsystem_cls = CoursierResolveSubsystem


class JvmResolvesToAddresses(FrozenDict[str, FrozenOrderedSet[Address]]):
    pass


@rule
async def map_resolves_to_consuming_targets(
    all_targets: AllTargets, jvm: JvmSubsystem
) -> JvmResolvesToAddresses:
    resolve_to_addresses = defaultdict(set)
    for tgt in all_targets:
        if tgt.has_field(JvmResolveField):
            resolve = tgt[JvmResolveField].value or jvm.default_resolve
            # TODO: remove once we always have a default resolve.
            if not resolve:
                continue
            resolve_to_addresses[resolve].add(tgt.address)
        elif tgt.has_field(JvmCompatibleResolvesField):
            # TODO: add a `default_compatible_resolves` field.
            resolves: Sequence[str] = tgt[JvmCompatibleResolvesField].value or (
                [jvm.default_resolve] if jvm.default_resolve is not None else []
            )
            for resolve in resolves:
                resolve_to_addresses[resolve].add(tgt.address)
    return JvmResolvesToAddresses(
        (resolve, FrozenOrderedSet(addresses))
        for resolve, addresses in resolve_to_addresses.items()
    )


@dataclass(frozen=True)
class CoursierGenerateLockfileRequest:
    """Regenerate a coursier_lockfile target's lockfile from its JVM requirements.

    This request allows a user to manually regenerate their lockfile. This is done for a few reasons: to
    generate the lockfile for the first time, to regenerate it because the input JVM requirements
    have changed, or to regenerate it to check if the resolve has changed (e.g. due to newer
    versions of dependencies being published).

    resolve: The name of the resolve config to compare
    """

    resolve: str


@dataclass(frozen=True)
class CoursierGenerateLockfileResult:
    digest: Digest


@rule
async def coursier_generate_lockfile(
    request: CoursierGenerateLockfileRequest,
    jvm: JvmSubsystem,
    resolves_to_addresses: JvmResolvesToAddresses,
) -> CoursierGenerateLockfileResult:
    # Find JVM artifacts in the dependency tree of the targets that depend on this lockfile.
    # These artifacts constitute the requirements that will be resolved for this lockfile.
    dependee_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(resolves_to_addresses.get(request.resolve, ()))
    )
    artifact_requirements = ArtifactRequirements(
        ArtifactRequirement.from_jvm_artifact_target(tgt)
        for tgt in dependee_targets.closure
        if JvmArtifactFieldSet.is_applicable(tgt)
    )

    resolved_lockfile = await Get(
        CoursierResolvedLockfile, ArtifactRequirements, artifact_requirements
    )
    resolved_lockfile_json = resolved_lockfile.to_json()
    lockfile_path = jvm.resolves[request.resolve]

    # If the lockfile hasn't changed, don't overwrite it.
    existing_lockfile_digest_contents = await Get(DigestContents, PathGlobs([lockfile_path]))
    if (
        existing_lockfile_digest_contents
        and resolved_lockfile_json == existing_lockfile_digest_contents[0].content
    ):
        return CoursierGenerateLockfileResult(EMPTY_DIGEST)

    new_lockfile = await Get(
        Digest, CreateDigest((FileContent(lockfile_path, resolved_lockfile_json),))
    )
    return CoursierGenerateLockfileResult(new_lockfile)


@goal_rule
async def coursier_resolve_lockfiles(
    console: Console,
    resolve_subsystem: CoursierResolveSubsystem,
    jvm: JvmSubsystem,
    workspace: Workspace,
) -> CoursierResolve:
    resolves = resolve_subsystem.options.names
    available_resolves = set(jvm.resolves.keys())
    if not resolves:
        # Default behaviour is to resolve everything.
        resolves = available_resolves
    else:
        invalid_resolve_names = set(resolves) - available_resolves
        if invalid_resolve_names:
            raise CoursierError(
                "The following resolve names are not defined in `[jvm].resolves`: "
                f"{invalid_resolve_names}\n\n"
                f"The valid resolve names are: {available_resolves}"
            )

    results = await MultiGet(
        Get(CoursierGenerateLockfileResult, CoursierGenerateLockfileRequest(resolve))
        for resolve in resolves
    )

    # For performance reasons, avoid writing out files to the workspace that haven't changed.
    results_to_write = tuple(result for result in results if result.digest != EMPTY_DIGEST)
    if results_to_write:
        merged_snapshot = await Get(
            Snapshot, MergeDigests(result.digest for result in results_to_write)
        )
        workspace.write_digest(merged_snapshot.digest)
        for path in merged_snapshot.files:
            console.print_stderr(f"Updated lockfile at: {path}")

    return CoursierResolve(exit_code=0)


def rules():
    return [*collect_rules()]
