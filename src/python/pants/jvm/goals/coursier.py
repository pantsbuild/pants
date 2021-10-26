# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.addresses import Addresses, UnparsedAddressInputs
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
from pants.engine.target import (
    AllTargets,
    InvalidTargetException,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    CoursierError,
    CoursierResolvedLockfile,
)
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactFieldSet,
    JvmArtifactGroupField,
    JvmArtifactVersionField,
    JvmCompatibleResolveNamesField,
    JvmRequirementsField,
)
from pants.util.logging import LogLevel


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
                "A list of resolve names to resolve. If not provided, resolve all known resolves."
            ),
        )


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
class JvmTargetsByResolveName:
    targets_by_resolve_name: dict[str, Targets]


@rule
async def get_jvm_targets_by_resolve_name(
    all_targets: AllTargets,
    jvm: JvmSubsystem,
) -> JvmTargetsByResolveName:
    # Get all targets that depend on JVM resolves

    targets = [tgt for tgt in all_targets if tgt.has_field(JvmCompatibleResolveNamesField)]

    default_resolve: str | None = jvm.options.default_resolve

    # TODO: simplify this with Py3.9 walrus operator
    flat_targets_ = ((tgt, tgt[JvmCompatibleResolveNamesField].value) for tgt in targets)
    flat_targets__ = (
        (
            tgt,
            names
            if names is not None
            else (default_resolve,)
            if default_resolve is not None
            else None,
        )
        for (tgt, names) in flat_targets_
    )
    flat_targets = [
        (name, tgt) for (tgt, names) in flat_targets__ if names is not None for name in names
    ]

    targets_by_resolve_name = {
        i: Targets(k[1] for k in j) for (i, j) in groupby(flat_targets, lambda x: x[0])
    }

    return JvmTargetsByResolveName(targets_by_resolve_name)


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
    targets_by_resolve_name: JvmTargetsByResolveName,
) -> CoursierGenerateLockfileResult:

    # `targets_by_resolve_name` supplies all of the targets that depend on each JVM resolve, so
    # no need to find transitive deps?

    # This task finds all of the sources that depend on this lockfile, and then resolves
    # a lockfile that satisfies all of their `jvm_artifact` dependencies.

    targets = targets_by_resolve_name.targets_by_resolve_name[request.resolve]

    # Find JVM artifacts in the dependency tree of the targets that depend on this lockfile.
    # These artifacts constitute the requirements that will be resolved for this lockfile.
    dependee_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(tgt.address for tgt in targets)
    )
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

    lockfile_path = jvm.options.resolves[request.resolve]

    # Materialise the existing lockfile, and check for changes. We don't want to re-write
    # identical lockfiles
    existing_lockfile_source = PathGlobs(
        [lockfile_path],
        glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
    )
    existing_lockfile_digest_contents = await Get(
        DigestContents, PathGlobs, existing_lockfile_source
    )

    if not existing_lockfile_digest_contents:
        # The user defined the target and resolved it, but hasn't created a lockfile yet.
        # For convenience, create the initial lockfile for them in the specified path.
        return CoursierGenerateLockfileResult(
            digest=await Get(
                Digest,
                CreateDigest(
                    (
                        FileContent(
                            path=lockfile_path,
                            content=resolved_lockfile_json,
                        ),
                    )
                ),
            )
        )

    existing_lockfile_json = existing_lockfile_digest_contents[0].content

    if resolved_lockfile_json != existing_lockfile_json:
        # The generated lockfile differs from the existing one, so return the digest of the generated one.
        return CoursierGenerateLockfileResult(
            digest=await Get(
                Digest,
                CreateDigest((FileContent(path=lockfile_path, content=resolved_lockfile_json),)),
            )
        )
    # The generated lockfile didn't change, so return an empty digest.
    return CoursierGenerateLockfileResult(
        digest=EMPTY_DIGEST,
    )


@goal_rule
async def coursier_resolve_lockfiles(
    console: Console,
    resolve_subsystem: CoursierResolveSubsystem,
    jvm: JvmSubsystem,
    workspace: Workspace,
) -> CoursierResolve:

    resolves = resolve_subsystem.options.names
    available_resolves = set(jvm.options.resolves.keys())
    if not resolves:
        # Default behaviour is to reconcile every known resolve (this is expensive, but *shrug*)
        resolves = available_resolves
    else:
        invalid_resolve_names = set(resolves) - available_resolves
        if invalid_resolve_names:
            raise CoursierError(
                "The following resolve names are not names of actual resolves: "
                f"{invalid_resolve_names}. The valid resolve names are {available_resolves}."
            )

    results = await MultiGet(
        Get(CoursierGenerateLockfileResult, CoursierGenerateLockfileRequest(resolve=resolve))
        for resolve in resolves
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
