# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.console import Console
from pants.engine.fs import CreateDigest, DigestContents, FileContent, PathGlobs, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.jvm.compile import ClasspathEntry
from pants.jvm.dependency_inference.artifact_mapper import AllJvmArtifactTargets
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    InvalidCoordinateString,
)
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.option.option_types import ArgsListOption, StrOption
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class JvmAddArtifactSubsystem(GoalSubsystem):
    name = "jvm-add-artifact"
    help = "Add a `jvm_artifact` target to a BUILD file."

    coordinates = ArgsListOption(
        flag_name="--coordinates",
        example="com.google.guava:guava:31.1-jre",
        passthrough=True,
    )

    build_file_path_template = StrOption(
        "--build-file-path",
        default="3rdparty/jvm/{group_path}/BUILD",
        help=softwrap(
            """\
            Path to the BUILD file where to write the `jvm_artifact` target for a JVM artifact. The value of this
            option is a template. Use `{group_path}` to have the `group` part of the artifact transformed into
            a path.
            """
        ),
    )


class JvmAddArtifact(Goal):
    subsystem_cls = JvmAddArtifactSubsystem


@dataclass(frozen=True)
class RenderJvmArtifactTargetRequest:
    coordinate_str: str


@dataclass(frozen=True)
class RenderJvmArtifactTargetResult:
    build_file_content: str
    build_file_path: str
    message: str
    is_error: bool = False


def _get_entry_for_coord(
    lockfile: CoursierResolvedLockfile, coord: Coordinate
) -> CoursierLockfileEntry | None:
    for entry in lockfile.entries:
        if entry.coord == coord:
            return entry
    return None


def _jar_filenames_to_symbols(filenames: Iterable[str]) -> frozenset[str]:
    symbols: set[str] = set()
    for filename in filenames:
        if not filename.endswith(".class"):
            continue
        stripped_filename = filename[: -len(".class")]
        symbols.add(stripped_filename.replace("/", "."))
    return frozenset(symbols)


def _symbols_to_packages(symbols: frozenset[str]) -> tuple[str, ...]:
    packages: set[str] = set()
    for symbol in symbols:
        package, _, _ = symbol.rpartition(".")
        packages.add(package)
    return tuple(sorted(frozenset(packages)))


@rule
async def render_jvm_artifact_target_for_build_file(
    request: RenderJvmArtifactTargetRequest,
    all_jvm_artifacts: AllJvmArtifactTargets,
    unzip: UnzipBinary,
    goal_subsystem: JvmAddArtifactSubsystem,
) -> RenderJvmArtifactTargetResult:
    try:
        coordinate = Coordinate.from_coord_str(request.coordinate_str)
    except InvalidCoordinateString:
        return RenderJvmArtifactTargetResult(
            build_file_content="",
            build_file_path="",
            message="This coordinate string is not in the correct format.",
            is_error=True,
        )

    # Scan all `jvm_artifact` targets to see if this target is already defined.
    for tgt in all_jvm_artifacts:
        req = ArtifactRequirement.from_jvm_artifact_target(tgt)
        if (
            req.coordinate.group == coordinate.group
            and req.coordinate.artifact == coordinate.artifact
        ):
            if req.coordinate.version == coordinate.version:
                message = f"A `jvm_artifact` is already defined at {tgt.address}."
            else:
                message = f"A `jvm_artifact` is already defined at {tgt.address}, but has version `{req.coordinate.version}`."
            return RenderJvmArtifactTargetResult(
                build_file_content="", build_file_path="", message=message
            )

    # Resolve this artifact and fetch the applicable jar.
    lockfile = await Get(
        CoursierResolvedLockfile, ArtifactRequirements([ArtifactRequirement(coordinate)])
    )
    lockfile_entry = _get_entry_for_coord(lockfile, coordinate)
    if not lockfile_entry:
        return RenderJvmArtifactTargetResult(
            build_file_content="",
            build_file_path="",
            message=f"Illegal state: Attempted to resolve {coordinate}, but the coordinate was not found in the resolution.",
            is_error=True,
        )

    classpath_entry = await Get(ClasspathEntry, CoursierLockfileEntry, lockfile_entry)
    filenames_result = await Get(
        ProcessResult,
        Process(
            argv=[unzip.path, "-Z", "-1", classpath_entry.filenames[0]],
            input_digest=classpath_entry.digest,
            description=f"Extract filenames from jar {classpath_entry.filenames[0]}.",
            level=LogLevel.DEBUG,
        ),
    )
    filenames = filenames_result.stdout.decode().strip().splitlines()
    symbols = _jar_filenames_to_symbols(filenames)
    packages = _symbols_to_packages(symbols)
    needs_packages = any(not pkg.startswith(coordinate.group) for pkg in packages)

    fields = [
        "jvm_artifact(",
        f"""    name="{coordinate.group}_{coordinate.artifact}",""",
        f"""    group="{coordinate.group}",""",
        f"""    artifact="{coordinate.artifact}",""",
        f"""    version="{coordinate.version}",""",
    ]
    if needs_packages:
        fields.extend(
            [
                f"    # NEEDS EDIT: This jvm_artifact contains classes that do not match the group `{coordinate.group}`.",
                "    # Please edit the `packages` field below as appropriate to contain wildcards for those classes",
                "    # to enable dependency inference to automatically infer dependencies on this target. A suggested",
                "    # list of package wildcards is provided, but may not be perfectly accurate.",
                "    packages=[",
                *(f'        "{pkg}.**",' for pkg in packages),
                "    ],",
            ]
        )
    fields.append(")")

    build_file_content = "\n".join(fields)

    build_file_path_template = goal_subsystem.build_file_path_template
    build_file_path = build_file_path_template.format(
        group_path="/".join(coordinate.group.split("."))
    )

    return RenderJvmArtifactTargetResult(
        build_file_content=build_file_content,
        build_file_path=build_file_path,
        message=f"Found jar. Writing target to build file at {build_file_path}.",
    )


@goal_rule
async def jvm_add_artifact(
    console: Console, workspace: Workspace, goal_subsystem: JvmAddArtifactSubsystem
) -> JvmAddArtifact:
    results = await MultiGet(
        Get(RenderJvmArtifactTargetResult, RenderJvmArtifactTargetRequest(coordinate_str))
        for coordinate_str in goal_subsystem.coordinates
    )
    for coordinate_str, result in zip(goal_subsystem.coordinates, results):
        console.write_stdout(f"{coordinate_str}: {result.message}\n")

    for result in results:
        if result.is_error:
            continue

        existing_build_file_contents: str = ""
        existing_build_file_digest = await Get(Digest, PathGlobs([result.build_file_path]))
        if existing_build_file_digest != EMPTY_DIGEST:
            digest_contents = await Get(DigestContents, Digest, existing_build_file_digest)
            assert len(digest_contents) == 1
            existing_build_file_contents = digest_contents[0].content.decode()

        needs_newline = existing_build_file_contents and not existing_build_file_contents.endswith(
            "\n"
        )
        new_build_file_contents = (
            existing_build_file_contents
            + ("\n" if needs_newline else "")
            + result.build_file_content
        )
        new_build_file_digest = await Get(
            Digest,
            CreateDigest([FileContent(result.build_file_path, new_build_file_contents.encode())]),
        )
        workspace.write_digest(new_build_file_digest)

    return JvmAddArtifact(exit_code=0 if all(not r.is_error for r in results) else 1)


def rules():
    return collect_rules()
