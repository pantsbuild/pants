# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from typing import FrozenSet, List, Tuple

from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    GenerateLockfilesSubsystem,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
    WrappedGenerateLockfile,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    FileDigest,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionRule
from pants.jvm.resolve import coursier_fetch, jvm_tool
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    CoursierResolveKey,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.jvm.resolve.jvm_tool import GatherJvmCoordinatesRequest, JvmToolBase
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmArtifactCompatibleResolvesField, JvmArtifactJarSourceField
from pants.jvm.util_rules import ExtractFileDigest
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

# -----------------------------------------------------------------------
# Tool lockfiles
# -----------------------------------------------------------------------


@dataclass(frozen=True)
class GenerateJvmLockfile(GenerateLockfile):
    artifacts: ArtifactRequirements


def _classpath_dest_filename(coord: str, src_filename: str) -> str:
    """Calculates the destination filename on the classpath for the given source filename and coord.

    TODO: This is duplicated in `COURSIER_POST_PROCESSING_SCRIPT`.
    """
    dest_name = coord.replace(":", "_")
    _, ext = os.path.splitext(src_filename)
    return f"{dest_name}{ext}"


@dataclass(frozen=True)
class _CoursierResolveInfo:
    coord_arg_strings: FrozenSet[str]
    digest: Digest


@rule
async def prepare_coursier_resolve_info(
    artifact_requirements: ArtifactRequirements,
) -> _CoursierResolveInfo:
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

    return _CoursierResolveInfo(
        coord_arg_strings=frozenset(req.to_coord_arg_str() for req in to_resolve),
        digest=jar_files.snapshot.digest,
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

    coursier_resolve_info = await Get(
        _CoursierResolveInfo, ArtifactRequirements, artifact_requirements
    )

    coursier_report_file_name = "coursier_report.json"
    process_result = await Get(
        ProcessResult,
        Process(
            argv=coursier.args(
                [
                    coursier_report_file_name,
                    *coursier_resolve_info.coord_arg_strings,
                    # TODO(#13496): Disable --strict-include to work around Coursier issue
                    # https://github.com/coursier/coursier/issues/1364 which erroneously rejects underscores in
                    # artifact rules as malformed.
                    # *(
                    #     f"--strict-include={req.to_coord_str(versioned=False)}"
                    #     for req in artifact_requirements
                    #     if req.strict
                    # ),
                ],
                wrapper=[bash.path, coursier.wrapper_script],
            ),
            input_digest=coursier_resolve_info.digest,
            immutable_input_digests=coursier.immutable_input_digests,
            output_directories=("classpath",),
            output_files=(coursier_report_file_name,),
            append_only_caches=coursier.append_only_caches,
            env=coursier.env,
            description=(
                "Running `coursier fetch` against "
                f"{pluralize(len(artifact_requirements), 'requirement')}: "
                f"{', '.join(req.to_coord_arg_str() for req in artifact_requirements)}"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    report_digest = await Get(
        Digest, DigestSubset(process_result.output_digest, PathGlobs([coursier_report_file_name]))
    )
    report_contents = await Get(DigestContents, Digest, report_digest)
    report = json.loads(report_contents[0].content)

    artifact_file_names = tuple(
        _classpath_dest_filename(dep["coord"], dep["file"]) for dep in report["dependencies"]
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


@rule
async def load_jvm_lockfile(
    request: GenerateJvmLockfile,
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


# -----------------------------------------------------------------------
# Tool lockfiles
# -----------------------------------------------------------------------


@frozen_after_init
@dataclass(unsafe_hash=True)
class GenerateJvmLockfileFromTool:
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
    request: GenerateJvmLockfileFromTool,
) -> GenerateJvmLockfile:
    artifacts = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(
            request.artifact_inputs,
            f"[{request.options_scope}].artifacts",
        ),
    )
    return GenerateJvmLockfile(
        artifacts=artifacts,
        resolve_name=request.options_scope,
        lockfile_dest=request.lockfile_dest,
    )


@rule
def wrap_jvm_lockfile_request(request: GenerateJvmLockfile) -> WrappedGenerateLockfile:
    return WrappedGenerateLockfile(request)


# -----------------------------------------------------------------------
# User lockfiles
# -----------------------------------------------------------------------


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
        *jvm_tool.rules(),
        UnionRule(GenerateLockfile, GenerateJvmLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownJVMUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedJVMserResolveNames),
    )
