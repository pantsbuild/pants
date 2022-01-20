# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable, Iterator

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.collection import Collection
from pants.engine.fs import (
    AddPrefix,
    Digest,
    DigestContents,
    DigestSubset,
    FileDigest,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Target, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.goals.lockfile import _classpath_dest_filename, _CoursierResolveInfo
from pants.jvm.resolve import coursier_setup
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    CoursierError,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    CoursierResolveKey,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactFieldSet, JvmArtifactJarSourceField
from pants.jvm.util_rules import ExtractFileDigest
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


class CoursierFetchRequest(ClasspathEntryRequest):
    field_sets = (JvmArtifactFieldSet,)


class NoCompatibleResolve(Exception):
    """No compatible resolve could be found for a set of targets."""

    def __init__(self, jvm: JvmSubsystem, msg_prefix: str, incompatible_targets: Iterable[Target]):
        targets_and_resolves_str = bullet_list(
            f"{t.address.spec}\t{jvm.resolves_for_target(t)}" for t in incompatible_targets
        )
        super().__init__(
            f"{msg_prefix}:\n"
            f"{targets_and_resolves_str}\n"
            "Targets which will be merged onto the same classpath must have at least one compatible "
            f"resolve (from the [resolve]({doc_url('reference-deploy_jar#coderesolvecode')}) or "
            f"[compatible_resolves]({doc_url('reference-java_sources#codecompatible_resolvescode')}) "
            "fields) in common."
        )


@rule(desc="Fetch with coursier")
async def fetch_with_coursier(request: CoursierFetchRequest) -> FallibleClasspathEntry:
    # TODO: Loading this per JvmArtifact.
    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, request.resolve)

    requirement = ArtifactRequirement.from_jvm_artifact_target(request.component.representative)

    if lockfile.metadata and not lockfile.metadata.is_valid_for([requirement]):
        raise ValueError(
            f"Requirement `{requirement.to_coord_arg_str()}` has changed since the lockfile "
            f"for {request.resolve.path} was generated. Run `./pants generate-lockfiles` to update your "
            "lockfile based on the new requirements."
        )

    # All of the transitive dependencies are exported.
    # TODO: Expose an option to control whether this exports only the root, direct dependencies,
    # transitive dependencies, etc.
    assert len(request.component.members) == 1, "JvmArtifact does not have dependencies."
    root_entry, transitive_entries = lockfile.dependencies(
        request.resolve,
        requirement.coordinate,
    )

    classpath_entries = await MultiGet(
        Get(ClasspathEntry, CoursierLockfileEntry, entry)
        for entry in (root_entry, *transitive_entries)
    )
    exported_digest = await Get(Digest, MergeDigests(cpe.digest for cpe in classpath_entries))

    return FallibleClasspathEntry(
        description=str(request.component),
        result=CompileResult.SUCCEEDED,
        output=ClasspathEntry.merge(exported_digest, classpath_entries),
        exit_code=0,
    )


class ResolvedClasspathEntries(Collection[ClasspathEntry]):
    """A collection of resolved classpath entries."""


@rule
async def coursier_fetch_one_coord(
    bash: BashBinary,
    coursier: Coursier,
    request: CoursierLockfileEntry,
) -> ClasspathEntry:
    """Run `coursier fetch --intransitive` to fetch a single artifact.

    This rule exists to permit efficient subsetting of a "global" classpath
    in the form of a lockfile.  Callers can determine what subset of dependencies
    from the lockfile are needed for a given target, then request those
    lockfile entries individually.

    By fetching only one entry at a time, we maximize our cache efficiency.  If instead
    we fetched the entire subset that the caller wanted, there would be a different cache
    key for every possible subset.

    This rule also guarantees exact reproducibility.  If all caches have been
    removed, `coursier fetch` will re-download the artifact, and this rule will
    confirm that what was downloaded matches exactly (by content digest) what
    was specified in the lockfile (what Coursier originally downloaded).
    """

    # Prepare any URL- or JAR-specifying entries for use with Coursier
    req: ArtifactRequirement
    if request.pants_address:
        targets = await Get(
            Targets, UnparsedAddressInputs([request.pants_address], owning_address=None)
        )
        req = ArtifactRequirement(request.coord, jar=targets[0][JvmArtifactJarSourceField])
    else:
        req = ArtifactRequirement(request.coord, url=request.remote_url)

    coursier_resolve_info = await Get(
        _CoursierResolveInfo,
        ArtifactRequirements([req]),
    )

    coursier_report_file_name = "coursier_report.json"
    process_result = await Get(
        ProcessResult,
        Process(
            argv=coursier.args(
                [
                    coursier_report_file_name,
                    "--intransitive",
                    *coursier_resolve_info.coord_arg_strings,
                ],
                wrapper=[bash.path, coursier.wrapper_script],
            ),
            input_digest=coursier_resolve_info.digest,
            immutable_input_digests=coursier.immutable_input_digests,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            append_only_caches=coursier.append_only_caches,
            env=coursier.env,
            description=f"Fetching with coursier: {request.coord.to_coord_str()}",
            level=LogLevel.DEBUG,
        ),
    )
    report_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([coursier_report_file_name]))
    )
    report_contents = await Get(DigestContents, Digest, report_digest)
    report = json.loads(report_contents[0].content)

    report_deps = report["dependencies"]
    if len(report_deps) == 0:
        raise CoursierError("Coursier fetch report has no dependencies (i.e. nothing was fetched).")
    elif len(report_deps) > 1:
        raise CoursierError(
            "Coursier fetch report has multiple dependencies, but exactly 1 was expected."
        )

    dep = report_deps[0]
    resolved_coord = Coordinate.from_coord_str(dep["coord"])
    if resolved_coord != request.coord:
        raise CoursierError(
            f'Coursier resolved coord "{resolved_coord.to_coord_str()}" does not match requested coord "{request.coord.to_coord_str()}".'
        )

    classpath_dest_name = _classpath_dest_filename(dep["coord"], dep["file"])
    classpath_dest = f"classpath/{classpath_dest_name}"

    resolved_file_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([classpath_dest]))
    )
    stripped_digest = await Get(Digest, RemovePrefix(resolved_file_digest, "classpath"))
    file_digest = await Get(
        FileDigest,
        ExtractFileDigest(stripped_digest, classpath_dest_name),
    )
    if file_digest != request.file_digest:
        raise CoursierError(
            f"Coursier fetch for '{resolved_coord}' succeeded, but fetched artifact {file_digest} did not match the expected artifact: {request.file_digest}."
        )
    return ClasspathEntry(digest=stripped_digest, filenames=(classpath_dest_name,))


@rule(level=LogLevel.DEBUG)
async def coursier_fetch_lockfile(lockfile: CoursierResolvedLockfile) -> ResolvedClasspathEntries:
    """Fetch every artifact in a lockfile."""
    classpath_entries = await MultiGet(
        Get(ClasspathEntry, CoursierLockfileEntry, entry) for entry in lockfile.entries
    )
    return ResolvedClasspathEntries(classpath_entries)


@rule
async def select_coursier_resolve_for_targets(
    coarsened_targets: CoarsenedTargets, jvm: JvmSubsystem
) -> CoursierResolveKey:
    """Selects and validates (transitively) a single resolve for a set of roots in a compile graph.

    In most cases, a `CoursierResolveKey` should be requested for a single `CoarsenedTarget` root,
    which avoids coupling un-related roots unnecessarily. But in other cases, a single compatible
    resolve is required for multiple roots (such as when running a `repl` over unrelated code), and
    in that case there might be multiple CoarsenedTargets.
    """
    root_targets = [t for ct in coarsened_targets for t in ct.members]

    # Find the set of resolves that are compatible with all roots by ANDing them all together.
    compatible_resolves: set[str] | None = None
    for tgt in root_targets:
        current_resolves = set(jvm.resolves_for_target(tgt))
        if compatible_resolves is None:
            compatible_resolves = current_resolves
        else:
            compatible_resolves &= current_resolves

    # Select a resolve from the compatible set.
    if not compatible_resolves:
        raise NoCompatibleResolve(
            jvm, "The selected targets did not have a resolve in common", root_targets
        )
    # Take the first compatible resolve.
    resolve = min(compatible_resolves)

    # Validate that the selected resolve is compatible with all transitive dependencies.
    incompatible_targets = []
    for ct in coarsened_targets.closure():
        for t in ct.members:
            if not jvm.is_jvm_target(t):
                continue
            target_resolves = jvm.resolves_for_target(t)
            if target_resolves is not None and resolve not in target_resolves:
                incompatible_targets.append(t)
    if incompatible_targets:
        raise NoCompatibleResolve(
            jvm,
            f"The resolve chosen for the root targets was {resolve}, but some of their "
            "dependencies were not compatible with that resolve",
            incompatible_targets,
        )

    # Load the resolve.
    resolve_path = jvm.resolves[resolve]
    lockfile_source = PathGlobs(
        [resolve_path],
        glob_match_error_behavior=GlobMatchErrorBehavior.error,
        description_of_origin=f"The resolve `{resolve}` from `[jvm].resolves`",
    )
    resolve_digest = await Get(Digest, PathGlobs, lockfile_source)
    return CoursierResolveKey(resolve, resolve_path, resolve_digest)


@rule
async def get_coursier_lockfile_for_resolve(
    coursier_resolve: CoursierResolveKey,
) -> CoursierResolvedLockfile:
    lockfile_digest_contents = await Get(DigestContents, Digest, coursier_resolve.digest)
    lockfile_contents = lockfile_digest_contents[0].content
    return CoursierResolvedLockfile.from_serialized(lockfile_contents)


@dataclass(frozen=True)
class MaterializedClasspathRequest:
    """A helper to merge various classpath elements.

    :param prefix: if set, should be a relative directory that will
        be prepended to every classpath element.  This is useful for
        keeping all classpath elements isolated under a single directory
        in a process invocation, where other inputs on the process's
        root directory might interfere with un-prefixed classpath
        entries (or vice versa).
    """

    prefix: str | None = None
    lockfiles: tuple[CoursierResolvedLockfile, ...] = ()
    artifact_requirements: tuple[ArtifactRequirements, ...] = ()


@dataclass(frozen=True)
class MaterializedClasspath:
    """A fully fetched and merged classpath, ready to hand to a JVM process invocation.

    TODO: Consider renaming to reflect the fact that this is always a 3rdparty classpath.
    """

    content: Snapshot

    @property
    def digest(self) -> Digest:
        return self.content.digest

    def classpath_entries(self, root: str | None = None) -> Iterator[str]:
        """Returns optionally prefixed classpath entry filenames.

        :param prefix: if set, will be prepended to all entries.  This is useful
            if the process working directory is not the same as the root
            directory for the process input `Digest`.
        """
        if root is None:
            yield from self.content.files
            return

        for file_name in self.content.files:
            yield os.path.join(root, file_name)


@rule(level=LogLevel.DEBUG)
async def materialize_classpath(request: MaterializedClasspathRequest) -> MaterializedClasspath:
    """Resolve, fetch, and merge various classpath types to a single `Digest` and metadata."""

    artifact_requirements_lockfiles = await MultiGet(
        Get(CoursierResolvedLockfile, ArtifactRequirements, artifact_requirements)
        for artifact_requirements in request.artifact_requirements
    )

    lockfile_and_requirements_classpath_entries = await MultiGet(
        Get(
            ResolvedClasspathEntries,
            CoursierResolvedLockfile,
            lockfile,
        )
        for lockfile in (*request.lockfiles, *artifact_requirements_lockfiles)
    )
    merged_snapshot = await Get(
        Snapshot,
        MergeDigests(
            classpath_entry.digest
            for classpath_entries in lockfile_and_requirements_classpath_entries
            for classpath_entry in classpath_entries
        ),
    )
    if request.prefix is not None:
        merged_snapshot = await Get(Snapshot, AddPrefix(merged_snapshot.digest, request.prefix))
    return MaterializedClasspath(content=merged_snapshot)


def rules():
    return [
        *collect_rules(),
        *coursier_setup.rules(),
        UnionRule(ClasspathEntryRequest, CoursierFetchRequest),
    ]
