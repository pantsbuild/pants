# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import importlib.resources
import json
import logging
import os
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING, Any, FrozenSet, Iterable, Iterator, List, Tuple

import toml

from pants.base import deprecated
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateLockfilesSubsystem
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
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
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Target, Targets
from pants.engine.unions import UnionRule
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    CompileResult,
    FallibleClasspathEntry,
)
from pants.jvm.resolve import coursier_setup
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    GatherJvmCoordinatesRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier, CoursierWrapperProcess
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata, LockfileContext
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactFieldSet, JvmArtifactJarSourceField, JvmArtifactTarget
from pants.jvm.util_rules import ExtractFileDigest
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, pluralize

if TYPE_CHECKING:
    from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool

logger = logging.getLogger(__name__)


class CoursierFetchRequest(ClasspathEntryRequest):
    field_sets = (JvmArtifactFieldSet,)


class CoursierError(Exception):
    """An exception relating to invoking Coursier or processing its output."""


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


@dataclass(frozen=True)
class CoursierLockfileEntry:
    """A single artifact entry from a Coursier-resolved lockfile.

    These fields are nearly identical to the JSON objects from the
    "dependencies" entries in Coursier's --json-output-file format.
    But unlike Coursier's JSON report, a CoursierLockfileEntry
    includes the content-address of the artifact fetched by Coursier
    and ingested by Pants.

    For example, a Coursier JSON report dependency entry might look like this:

    ```
    {
      "coord": "com.chuusai:shapeless_2.13:2.3.3",
      "file": "/home/USER/.cache/coursier/v1/https/repo1.maven.org/maven2/com/chuusai/shapeless_2.13/2.3.3/shapeless_2.13-2.3.3.jar",
      "directDependencies": [
        "org.scala-lang:scala-library:2.13.0"
      ],
      "dependencies": [
        "org.scala-lang:scala-library:2.13.0"
      ]
    }
    ```

    The equivalent CoursierLockfileEntry would look like this:

    ```
    CoursierLockfileEntry(
        coord="com.chuusai:shapeless_2.13:2.3.3", # identical
        file_name="shapeless_2.13-2.3.3.jar" # PurePath(entry["file"].name)
        direct_dependencies=(Coordinate.from_coord_str("org.scala-lang:scala-library:2.13.0"),),
        dependencies=(Coordinate.from_coord_str("org.scala-lang:scala-library:2.13.0"),),
        file_digest=FileDigest(fingerprint=<sha256 of the jar>, ...),
    )
    ```

    The fields `remote_url` and `pants_address` are set by Pants if the `coord` field matches a
    `jvm_artifact` that had either the `url` or `jar` fields set.
    """

    coord: Coordinate
    file_name: str
    direct_dependencies: Coordinates
    dependencies: Coordinates
    file_digest: FileDigest
    remote_url: str | None = None
    pants_address: str | None = None

    @classmethod
    def from_json_dict(cls, entry) -> CoursierLockfileEntry:
        """Construct a CoursierLockfileEntry from its JSON dictionary representation."""

        return cls(
            coord=Coordinate.from_json_dict(entry["coord"]),
            file_name=entry["file_name"],
            direct_dependencies=Coordinates(
                Coordinate.from_json_dict(d) for d in entry["directDependencies"]
            ),
            dependencies=Coordinates(Coordinate.from_json_dict(d) for d in entry["dependencies"]),
            file_digest=FileDigest(
                fingerprint=entry["file_digest"]["fingerprint"],
                serialized_bytes_length=entry["file_digest"]["serialized_bytes_length"],
            ),
            remote_url=entry.get("remote_url"),
            pants_address=entry.get("pants_address"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Export this CoursierLockfileEntry to a JSON object."""

        return dict(
            coord=self.coord.to_json_dict(),
            directDependencies=[coord.to_json_dict() for coord in self.direct_dependencies],
            dependencies=[coord.to_json_dict() for coord in self.dependencies],
            file_name=self.file_name,
            file_digest=dict(
                fingerprint=self.file_digest.fingerprint,
                serialized_bytes_length=self.file_digest.serialized_bytes_length,
            ),
            remote_url=self.remote_url,
            pants_address=self.pants_address,
        )


@dataclass(frozen=True)
class CoursierResolvedLockfile:
    """An in-memory representation of Pants' Coursier lockfile format.

    All coordinates in the resolved lockfile will be compatible, so we do not need to do version
    testing when looking up coordinates.
    """

    entries: tuple[CoursierLockfileEntry, ...]
    metadata: JVMLockfileMetadata | None = None

    @classmethod
    def _coordinate_not_found(cls, key: CoursierResolveKey, coord: Coordinate) -> CoursierError:
        # TODO: After fixing https://github.com/pantsbuild/pants/issues/13496, coordinate matches
        # should become exact, and this error message will capture all cases of stale lockfiles.
        return CoursierError(
            f"{coord} was not present in resolve `{key.name}` at `{key.path}`.\n"
            f"If you have recently added new `{JvmArtifactTarget.alias}` targets, you might "
            f"need to update your lockfile by running `coursier-resolve --names={key.name}`."
        )

    def direct_dependencies(
        self, key: CoursierResolveKey, coord: Coordinate
    ) -> tuple[CoursierLockfileEntry, tuple[CoursierLockfileEntry, ...]]:
        """Return the entry for the given Coordinate, and for its direct dependencies."""
        entries = {(i.coord.group, i.coord.artifact): i for i in self.entries}
        entry = entries.get((coord.group, coord.artifact))
        if entry is None:
            raise self._coordinate_not_found(key, coord)

        return (entry, tuple(entries[(i.group, i.artifact)] for i in entry.direct_dependencies))

    def dependencies(
        self, key: CoursierResolveKey, coord: Coordinate
    ) -> tuple[CoursierLockfileEntry, tuple[CoursierLockfileEntry, ...]]:
        """Return the entry for the given Coordinate, and for its transitive dependencies."""
        entries = {(i.coord.group, i.coord.artifact): i for i in self.entries}
        entry = entries.get((coord.group, coord.artifact))
        if entry is None:
            raise self._coordinate_not_found(key, coord)

        return (entry, tuple(entries[(i.group, i.artifact)] for i in entry.dependencies))

    @classmethod
    def from_json_dicts(cls, json_lock_entries) -> CoursierResolvedLockfile:
        """Construct a CoursierResolvedLockfile from its JSON dictionary representation."""

        return cls(
            entries=tuple(CoursierLockfileEntry.from_json_dict(dep) for dep in json_lock_entries)
        )

    @classmethod
    def from_toml(cls, lockfile: str | bytes) -> CoursierResolvedLockfile:
        """Constructs a CoursierResolvedLockfile from it's TOML + metadata comment representation.

        The toml file should consist of an `[entries]` block, followed by several entries.
        """

        lockfile_str: str
        lockfile_bytes: bytes
        if isinstance(lockfile, str):
            lockfile_str = lockfile
            lockfile_bytes = lockfile.encode("utf-8")
        else:
            lockfile_str = lockfile.decode("utf-8")
            lockfile_bytes = lockfile

        contents = toml.loads(lockfile_str)
        entries = tuple(
            CoursierLockfileEntry.from_json_dict(entry) for entry in (contents["entries"])
        )
        metadata = JVMLockfileMetadata.from_lockfile(lockfile_bytes)

        return cls(
            entries=entries,
            metadata=metadata,
        )

    @classmethod
    def from_serialized(cls, lockfile: str | bytes) -> CoursierResolvedLockfile:
        """Construct a CoursierResolvedLockfile from its serialized representation (either TOML with
        attached metadata, or old-style JSON.)."""

        try:
            return cls.from_toml(lockfile)
        except toml.TomlDecodeError:
            deprecated.warn_or_error(
                "2.11.0.dev0",
                "JSON-encoded JVM lockfile",
                "Run `./pants generate-lockfiles` to generate lockfiles in the new format.",
            )
            return cls.from_json_dicts(json.loads(lockfile))

    def to_serialized(self) -> bytes:
        """Export this CoursierResolvedLockfile to a human-readable serialized form.

        This serialized form is intended to be checked in to the user's repo as a hermetic snapshot
        of a Coursier resolved JVM classpath.
        """

        lockfile = {
            "entries": [entry.to_json_dict() for entry in self.entries],
        }

        return toml.dumps(lockfile).encode("utf-8")


def classpath_dest_filename(coord: str, src_filename: str) -> str:
    """Calculates the destination filename on the classpath for the given source filename and coord.

    TODO: This is duplicated in `COURSIER_POST_PROCESSING_SCRIPT`.
    """
    dest_name = coord.replace(":", "_")
    _, ext = os.path.splitext(src_filename)
    return f"{dest_name}{ext}"


@dataclass(frozen=True)
class CoursierResolveInfo:
    coord_arg_strings: FrozenSet[str]
    digest: Digest


@rule
async def prepare_coursier_resolve_info(
    artifact_requirements: ArtifactRequirements,
) -> CoursierResolveInfo:
    # Transform requirements that correspond to local JAR files into coordinates with `file:/`
    # URLs, and put the files in the place specified by the URLs.
    no_jars: List[ArtifactRequirement] = []
    jars: List[Tuple[ArtifactRequirement, JvmArtifactJarSourceField]] = []

    for req in artifact_requirements:
        jar = req.jar
        if not jar:
            no_jars.append(req)
        else:
            jars.append((req, jar))

    jar_files = await Get(SourceFiles, SourceFilesRequest(i[1] for i in jars))
    jar_file_paths = jar_files.snapshot.files

    resolvable_jar_requirements = [
        dataclasses.replace(
            req, jar=None, url=f"file:{Coursier.working_directory_placeholder}/{path}"
        )
        for req, path in zip((i[0] for i in jars), jar_file_paths)
    ]

    to_resolve = chain(no_jars, resolvable_jar_requirements)

    return CoursierResolveInfo(
        coord_arg_strings=frozenset(req.to_coord_arg_str() for req in to_resolve),
        digest=jar_files.snapshot.digest,
    )


@rule(level=LogLevel.DEBUG)
async def coursier_resolve_lockfile(
    artifact_requirements: ArtifactRequirements,
) -> CoursierResolvedLockfile:
    """Run `coursier fetch ...` against a list of Maven coordinates and capture the result.

    This rule does two things in a single Process invocation:

        * Runs `coursier fetch` to let Coursier do the heavy lifting of resolving
          dependencies and downloading resolved artifacts (jars, etc).
        * Copies the resolved artifacts into the Process output directory, capturing
          the artifacts as content-addressed `Digest`s.

    It's important that this happens in the same process, since the process isn't
    guaranteed to run on the same machine as the rule, nor is a subsequent process
    invocation.  This guarantees that whatever Coursier resolved, it was fully
    captured into Pants' content addressed artifact storage.

    Note however that we still get the benefit of Coursier's "global" cache if it
    had already been run on the machine where the `coursier fetch` runs, so rerunning
    `coursier fetch` tends to be fast in practice.

    Finally, this rule bundles up the result into a `CoursierResolvedLockfile`.  This
    data structure encapsulates everything necessary to either materialize the
    resolved dependencies to a classpath for Java invocations, or to write the
    lockfile out to the workspace to hermetically freeze the result of the resolve.
    """

    if len(artifact_requirements) == 0:
        return CoursierResolvedLockfile(entries=())

    coursier_resolve_info = await Get(
        CoursierResolveInfo, ArtifactRequirements, artifact_requirements
    )

    coursier_report_file_name = "coursier_report.json"

    process_result = await Get(
        ProcessResult,
        CoursierWrapperProcess(
            args=(
                coursier_report_file_name,
                *coursier_resolve_info.coord_arg_strings,
            ),
            input_digest=coursier_resolve_info.digest,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            description=(
                "Running `coursier fetch` against "
                f"{pluralize(len(artifact_requirements), 'requirement')}: "
                f"{', '.join(req.to_coord_arg_str() for req in artifact_requirements)}"
            ),
        ),
    )

    report_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([coursier_report_file_name]))
    )
    report_contents = await Get(DigestContents, Digest, report_digest)
    report = json.loads(report_contents[0].content)

    artifact_file_names = tuple(
        classpath_dest_filename(dep["coord"], dep["file"]) for dep in report["dependencies"]
    )
    artifact_output_paths = tuple(f"classpath/{file_name}" for file_name in artifact_file_names)
    artifact_digests = await MultiGet(
        Get(Digest, DigestSubset(process_result.output_digest, PathGlobs([output_path])))
        for output_path in artifact_output_paths
    )
    stripped_artifact_digests = await MultiGet(
        Get(Digest, RemovePrefix(artifact_digest, "classpath"))
        for artifact_digest in artifact_digests
    )
    artifact_file_digests = await MultiGet(
        Get(FileDigest, ExtractFileDigest(stripped_artifact_digest, file_name))
        for stripped_artifact_digest, file_name in zip(
            stripped_artifact_digests, artifact_file_names
        )
    )

    first_pass_lockfile = CoursierResolvedLockfile(
        entries=tuple(
            CoursierLockfileEntry(
                coord=Coordinate.from_coord_str(dep["coord"]),
                direct_dependencies=Coordinates(
                    Coordinate.from_coord_str(dd) for dd in dep["directDependencies"]
                ),
                dependencies=Coordinates(Coordinate.from_coord_str(d) for d in dep["dependencies"]),
                file_name=file_name,
                file_digest=artifact_file_digest,
            )
            for dep, file_name, artifact_file_digest in zip(
                report["dependencies"], artifact_file_names, artifact_file_digests
            )
        )
    )

    inverted_artifacts = {req.coordinate: req for req in artifact_requirements}
    new_entries = []
    for entry in first_pass_lockfile.entries:
        req = inverted_artifacts.get(entry.coord)
        if req:
            address = req.jar.address if req.jar else None
            address_spec = address.spec if address else None
            entry = dataclasses.replace(entry, remote_url=req.url, pants_address=address_spec)
        new_entries.append(entry)

    return CoursierResolvedLockfile(entries=tuple(new_entries))


@rule(desc="Fetch with coursier")
async def fetch_with_coursier(request: CoursierFetchRequest) -> FallibleClasspathEntry:
    # TODO: Loading this per JvmArtifact.
    lockfile = await Get(CoursierResolvedLockfile, CoursierResolveKey, request.resolve)

    requirement = ArtifactRequirement.from_jvm_artifact_target(request.component.representative)

    if lockfile.metadata and not lockfile.metadata.is_valid_for(
        [requirement], LockfileContext.USER
    ):
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
        CoursierResolveInfo,
        ArtifactRequirements([req]),
    )

    coursier_report_file_name = "coursier_report.json"

    process_result = await Get(
        ProcessResult,
        CoursierWrapperProcess(
            args=(
                coursier_report_file_name,
                "--intransitive",
                *coursier_resolve_info.coord_arg_strings,
            ),
            input_digest=coursier_resolve_info.digest,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            description=f"Fetching with coursier: {request.coord.to_coord_str()}",
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

    classpath_dest_name = classpath_dest_filename(dep["coord"], dep["file"])
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
class ToolClasspathRequest:
    """A request to set up the classpath for a JVM tool by fetching artifacts and merging the
    classpath.

    :param prefix: if set, should be a relative directory that will
        be prepended to every classpath element.  This is useful for
        keeping all classpath elements isolated under a single directory
        in a process invocation, where other inputs on the process's
        root directory might interfere with un-prefixed classpath
        entries (or vice versa).
    """

    prefix: str | None = None
    lockfile: GenerateJvmLockfileFromTool | None = None
    artifact_requirements: ArtifactRequirements = ArtifactRequirements()

    def __post_init__(self) -> None:
        if not bool(self.lockfile) ^ bool(self.artifact_requirements):
            raise AssertionError(
                f"Exactly one of `lockfile` or `artifact_requirements` must be provided: {self}"
            )


@dataclass(frozen=True)
class ToolClasspath:
    """A fully fetched and merged classpath for running a JVM tool."""

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
async def materialize_classpath_for_tool(request: ToolClasspathRequest) -> ToolClasspath:
    if request.artifact_requirements:
        resolution = await Get(
            CoursierResolvedLockfile, ArtifactRequirements, request.artifact_requirements
        )
    else:
        lockfile_req = request.lockfile
        assert lockfile_req is not None
        regen_command = f"`{GenerateLockfilesSubsystem.name} --resolve={lockfile_req.resolve_name}`"
        if lockfile_req.lockfile_dest == DEFAULT_TOOL_LOCKFILE:
            lockfile_bytes = importlib.resources.read_binary(
                *lockfile_req.default_lockfile_resource
            )
            resolution = CoursierResolvedLockfile.from_serialized(lockfile_bytes)
        else:
            lockfile_snapshot = await Get(Snapshot, PathGlobs([lockfile_req.lockfile_dest]))
            if not lockfile_snapshot.files:
                raise ValueError(
                    f"No lockfile found at {lockfile_req.lockfile_dest}, which is configured "
                    f"by the option {lockfile_req.lockfile_option_name}."
                    f"Run {regen_command} to generate it."
                )

            resolution = await Get(
                CoursierResolvedLockfile,
                CoursierResolveKey(
                    name=lockfile_req.resolve_name,
                    path=lockfile_req.lockfile_dest,
                    digest=lockfile_snapshot.digest,
                ),
            )

        # Validate that the lockfile is correct.
        lockfile_inputs = await Get(
            ArtifactRequirements,
            GatherJvmCoordinatesRequest(
                lockfile_req.artifact_inputs, lockfile_req.artifact_option_name
            ),
        )
        if resolution.metadata and not resolution.metadata.is_valid_for(
            lockfile_inputs, LockfileContext.TOOL
        ):
            raise ValueError(
                f"The lockfile {lockfile_req.lockfile_dest} (configured by the option "
                f"{lockfile_req.lockfile_option_name}) was generated with different requirements "
                f"than are currently set via {lockfile_req.artifact_option_name}. Run "
                f"{regen_command} to regenerate the lockfile."
            )

    classpath_entries = await Get(ResolvedClasspathEntries, CoursierResolvedLockfile, resolution)
    merged_snapshot = await Get(
        Snapshot, MergeDigests(classpath_entry.digest for classpath_entry in classpath_entries)
    )
    if request.prefix is not None:
        merged_snapshot = await Get(Snapshot, AddPrefix(merged_snapshot.digest, request.prefix))
    return ToolClasspath(merged_snapshot)


def rules():
    return [
        *collect_rules(),
        *coursier_setup.rules(),
        UnionRule(ClasspathEntryRequest, CoursierFetchRequest),
    ]
