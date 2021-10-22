# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable, Iterator

from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import Collection, DeduplicatedCollection
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
from pants.engine.target import Targets, TransitiveTargets, TransitiveTargetsRequest
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.target_types import JvmLockfileSources, JvmRequirementsField
from pants.jvm.util_rules import ExtractFileDigest
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class CoursierError(Exception):
    """An exception relating to invoking Coursier or processing its output."""


@dataclass(frozen=True)
class Coordinate:
    """A single Maven-style coordinate for a JVM dependency."""

    group: str
    artifact: str
    version: str
    packaging: str = "jar"

    @staticmethod
    def from_json_dict(data: dict) -> Coordinate:
        return Coordinate(
            group=data["group"],
            artifact=data["artifact"],
            version=data["version"],
            packaging=data.get("packaging", "jar"),
        )

    def to_json_dict(self) -> dict:
        return {
            "group": self.group,
            "artifact": self.artifact,
            "version": self.version,
            "packaging": self.packaging,
        }

    @classmethod
    def from_coord_str(cls, s: str) -> Coordinate:
        parts = s.split(":")
        return cls(
            group=parts[0],
            artifact=parts[1],
            version=parts[2],
            packaging=parts[3] if len(parts) == 4 else "jar",
        )

    def to_coord_str(self) -> str:
        return f"{self.group}:{self.artifact}:{self.version}"


class Coordinates(DeduplicatedCollection[Coordinate]):
    """An ordered list of `Coordinate`s."""


# TODO: Consider whether to carry classpath scope in some fashion via ArtifactRequirements.
class ArtifactRequirements(DeduplicatedCollection[Coordinate]):
    """An ordered list of Coordinates used as requirements."""

    @classmethod
    def create_from_maven_coordinates_fields(
        cls,
        fields: Iterable[JvmRequirementsField],
        *,
        additional_requirements: Iterable[Coordinate] = (),
    ) -> ArtifactRequirements:
        field_requirements = (
            Coordinate.from_coord_str(str(maven_coord))
            for field in fields
            for maven_coord in (field.value or ())
        )
        return ArtifactRequirements((*field_requirements, *additional_requirements))


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
        direct_dependencies=(MavenCoord("org.scala-lang:scala-library:2.13.0"),),
        dependencies=(MavenCoord("org.scala-lang:scala-library:2.13.0"),),
        file_digest=FileDigest(fingerprint=<sha256 of the jar>, ...),
    )
    ```
    """

    coord: Coordinate
    file_name: str
    direct_dependencies: Coordinates
    dependencies: Coordinates
    file_digest: FileDigest

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
        )


@dataclass(frozen=True)
class CoursierResolvedLockfile:
    """An in-memory representation of Pants' Coursier lockfile format."""

    entries: tuple[CoursierLockfileEntry, ...]

    @classmethod
    def from_json_dict(cls, lockfile) -> CoursierResolvedLockfile:
        """Construct a CoursierResolvedLockfile from its JSON dictionary representation."""

        return cls(entries=tuple(CoursierLockfileEntry.from_json_dict(dep) for dep in lockfile))

    def to_json(self) -> bytes:
        """Export this CoursierResolvedLockfile to human-readable JSON.

        This JSON is intended to be checked in to the user's repo as a hermetic snapshot of a
        Coursier resolved JVM classpath.
        """
        return json.dumps([entry.to_json_dict() for entry in self.entries], indent=4).encode(
            "utf-8"
        )


@rule(level=LogLevel.DEBUG)
async def coursier_resolve_lockfile(
    bash: BashBinary,
    coursier: Coursier,
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

    coursier_report_file_name = "coursier_report.json"
    process_result = await Get(
        ProcessResult,
        Process(
            argv=coursier.args(
                [coursier_report_file_name, *(req.to_coord_str() for req in artifact_requirements)],
                wrapper=[bash.path, coursier.wrapper_script],
            ),
            input_digest=coursier.digest,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            append_only_caches=coursier.append_only_caches,
            description=(
                "Running `coursier fetch` against "
                f"{pluralize(len(artifact_requirements), 'requirement')}: "
                f"{', '.join(req.to_coord_str() for req in artifact_requirements)}"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    report_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([coursier_report_file_name]))
    )
    report_contents = await Get(DigestContents, Digest, report_digest)
    report = json.loads(report_contents[0].content)

    artifact_file_names = tuple(PurePath(dep["file"]).name for dep in report["dependencies"])
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
    return CoursierResolvedLockfile(
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


@dataclass(frozen=True)
class FetchOneCoordRequest:
    coord: Coordinate
    expected_digest: FileDigest


@dataclass(frozen=True)
class ResolvedClasspathEntry:
    """A single classpath entry from a resolver (e.g. Coursier), typically a jar."""

    coord: Coordinate
    file_name: str
    digest: Digest


class ResolvedClasspathEntries(Collection[ResolvedClasspathEntry]):
    """A collection of resolved classpath entries."""


@rule(level=LogLevel.DEBUG)
async def coursier_fetch_one_coord(
    bash: BashBinary,
    coursier: Coursier,
    request: CoursierLockfileEntry,
) -> ResolvedClasspathEntry:
    """Run `coursier fetch --intrasitive` to fetch a single artifact.

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
    coursier_report_file_name = "coursier_report.json"
    process_result = await Get(
        ProcessResult,
        Process(
            argv=coursier.args(
                [coursier_report_file_name, "--intransitive", request.coord.to_coord_str()],
                wrapper=[bash.path, coursier.wrapper_script],
            ),
            input_digest=coursier.digest,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            append_only_caches=coursier.append_only_caches,
            description="Run coursier resolve",
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

    file_path = PurePath(dep["file"])
    classpath_dest = f"classpath/{file_path.name}"

    resolved_file_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([classpath_dest]))
    )
    stripped_digest = await Get(Digest, RemovePrefix(resolved_file_digest, "classpath"))
    file_digest = await Get(
        FileDigest,
        ExtractFileDigest(stripped_digest, file_path.name),
    )
    if file_digest != request.file_digest:
        raise CoursierError(
            f"Coursier fetch for '{resolved_coord}' succeeded, but fetched artifact {file_digest} did not match the expected artifact: {request.file_digest}."
        )
    return ResolvedClasspathEntry(
        coord=request.coord, file_name=file_path.name, digest=stripped_digest
    )


@rule(level=LogLevel.DEBUG)
async def coursier_fetch_lockfile(lockfile: CoursierResolvedLockfile) -> ResolvedClasspathEntries:
    """Fetch every artifact in a lockfile."""
    classpath_entries = await MultiGet(
        Get(ResolvedClasspathEntry, CoursierLockfileEntry, entry) for entry in lockfile.entries
    )
    return ResolvedClasspathEntries(classpath_entries)


@rule(level=LogLevel.DEBUG)
async def load_coursier_lockfile_from_source(
    lockfile_field: JvmLockfileSources,
) -> CoursierResolvedLockfile:
    lockfile_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [lockfile_field],
            for_sources_types=[JvmLockfileSources],
            enable_codegen=False,
        ),
    )
    if len(lockfile_sources.files) != 1:
        raise CoursierError("JvmLockfileSources must have exactly 1 source file")

    source_lockfile_digest_contents = await Get(
        DigestContents, Digest, lockfile_sources.snapshot.digest
    )
    source_lockfile_content = source_lockfile_digest_contents[0]
    return CoursierResolvedLockfile.from_json_dict(json.loads(source_lockfile_content.content))


@dataclass(frozen=True)
class CoursierLockfileForTargetRequest:
    targets: Targets


@rule
async def get_coursier_lockfile_for_target(
    request: CoursierLockfileForTargetRequest,
) -> CoursierResolvedLockfile:
    """Determine the lockfile that applies to a given JVM target.

    Presently this just walks the target's transitive dependencies to find a dependency
    that provides `JvmLockfileSources`.

    This rule asserts that at most 1 such dependency may be in the JVM target's transitive
    dependencies.
    """

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(target.address for target in request.targets)
    )
    transitive_jvm_lockfile_sources = [
        target[JvmLockfileSources]
        for target in transitive_targets.closure
        if target.has_field(JvmLockfileSources)
    ]
    if len(transitive_jvm_lockfile_sources) == 0:
        raise CoursierError(
            "Exactly 1 target with a coursier_lockfile should appear in the transitive closure"
            " of a JVM target, but none were found."
        )

    if len(transitive_jvm_lockfile_sources) > 1:
        raise CoursierError(
            f"Exactly 1 target with a coursier_lockfile should appear in the transitive closure"
            f" of a JVM library, but {len(transitive_jvm_lockfile_sources)} were found."
        )
    jvm_lockfile_sources = transitive_jvm_lockfile_sources[0]
    lockfile_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [jvm_lockfile_sources],
            for_sources_types=[JvmLockfileSources],
            enable_codegen=False,
        ),
    )
    if len(lockfile_sources.files) != 1:
        raise CoursierError(
            f"JvmLockfileSources must have exactly 1 source file, but {jvm_lockfile_sources}"
            f" has {len(lockfile_sources.files)}"
        )

    source_lockfile_digest_contents = await Get(
        DigestContents, Digest, lockfile_sources.snapshot.digest
    )
    source_lockfile_content = source_lockfile_digest_contents[0]
    return CoursierResolvedLockfile.from_json_dict(json.loads(source_lockfile_content.content))


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
    resolved_classpaths: tuple[ResolvedClasspathEntries, ...] = ()
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
    all_classpath_entries = (
        *lockfile_and_requirements_classpath_entries,
        *request.resolved_classpaths,
    )
    merged_snapshot = await Get(
        Snapshot,
        MergeDigests(
            classpath_entry.digest
            for classpath_entries in all_classpath_entries
            for classpath_entry in classpath_entries
        ),
    )
    if request.prefix is not None:
        merged_snapshot = await Get(Snapshot, AddPrefix(merged_snapshot.digest, request.prefix))
    return MaterializedClasspath(content=merged_snapshot)


def rules():
    return [*collect_rules()]
