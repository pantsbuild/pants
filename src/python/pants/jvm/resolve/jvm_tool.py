# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import importlib.resources
import json
import logging
from dataclasses import dataclass
from typing import ClassVar, Iterable, Sequence, cast

from pants.backend.python.target_types import UnrecognizedResolveNamesError
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.unions import UnionMembership, union
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirements,
    Coordinate,
    CoursierResolvedLockfile,
)
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

DEFAULT_TOOL_LOCKFILE = "<default>"
NO_TOOL_LOCKFILE = "<none>"


logger = logging.getLogger(__name__)


class JvmToolBase(Subsystem):
    """Base class for subsystems that configure a set of artifact requirements for a JVM tool."""

    # Default version of the tool. (Subclasses must set.)
    default_version: ClassVar[str]

    # Default artifacts for the tool in GROUP:NAME format. The `--version` value will be used for the
    # artifact version if it has not been specified for a particular requirement. (Subclasses must set.)
    default_artifacts: ClassVar[Sequence[str]]

    # Default extra requirements for the tool. (Subclasses do not need to override.)
    default_extra_artifacts: ClassVar[Sequence[str]] = []

    # Default resource for the tool's lockfile. (Subclasses must set.)
    default_lockfile_resource: ClassVar[tuple[str, str]]

    default_lockfile_url: ClassVar[str | None] = None

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            advanced=True,
            default=cls.default_version,
            help=(
                "Version string for the tool. This will be substituted for any unspecified version in "
                "the --artifacts value."
            ),
        )
        register(
            "--artifacts",
            type=list,
            member_type=str,
            advanced=True,
            default=cls.default_artifacts,
            help=(
                "Artifact requirements for this tool using colon-separated form for the Maven coordinates. "
                "The string %VERSION% version will be substituted with the --version value."
            ),
        )
        register(
            "--extra-artifacts",
            type=list,
            member_type=str,
            advanced=True,
            default=cls.default_extra_artifacts,
            help="Any additional artifact requirement strings to use with the tool. This is useful if the "
            "tool allows you to install plugins or if you need to constrain a dependency to "
            "a certain version.",
        )
        register(
            "--lockfile",
            type=str,
            default=cls.default_lockfile_path,
            advanced=True,
            # TODO: Fix up the help text to not be Python-focused.
            help=(
                "Path to a lockfile used for installing the tool.\n\n"
                f"Set to the string `{DEFAULT_TOOL_LOCKFILE}` to use a lockfile provided by "
                "Pants, so long as you have not changed the `--version` and "
                "`--extra-requirements` options, and the tool's interpreter constraints are "
                "compatible with the default. Pants will error or warn if the lockfile is not "
                "compatible (controlled by `[python].invalid_lockfile_behavior`). See "
                f"{cls.default_lockfile_url} for the default lockfile contents.\n\n"
                f"Set to the string `{NO_TOOL_LOCKFILE}` to opt out of using a lockfile. We "
                f"do not recommend this, though, as lockfiles are essential for reproducible "
                f"builds.\n\n"
                "To use a custom lockfile, set this option to a file path relative to the "
                f"build root, then run `./pants generate-lockfiles "
                f"--resolve={cls.options_scope}`.\n\n"
                "Lockfile generation currently does not wire up the `[python-repos]` options. "
                "If lockfile generation fails, you can manually generate a lockfile, such as "
                "by using pip-compile or `pip freeze`. Set this option to the path to your "
                "manually generated lockfile. When manually maintaining lockfiles, set "
                "`[python].invalid_lockfile_behavior = 'ignore'`."
            ),
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def artifacts(self) -> tuple[Coordinate, ...]:
        return tuple(
            Coordinate.from_coord_str(s.replace("%VERSION%", self.version))
            for s in self.options.artifacts
        )

    @property
    def extra_artifacts(self) -> tuple[Coordinate, ...]:
        return tuple(Coordinate.from_coord_str(s) for s in self.options.extra_artifacts)

    @property
    def lockfile(self) -> str:
        f"""The path to a lockfile or special string '{DEFAULT_TOOL_LOCKFILE}'."""
        lockfile = cast(str, self.options.lockfile)
        if lockfile != DEFAULT_TOOL_LOCKFILE:
            return lockfile
        pkg, path = self.default_lockfile_resource
        return f"src/python/{pkg.replace('.', '/')}/{path}"

    def lockfile_content(self) -> bytes:
        lockfile_path = self.lockfile
        if lockfile_path == DEFAULT_TOOL_LOCKFILE:
            return importlib.resources.read_binary(*self.default_lockfile_resource)
        with open(lockfile_path, "rb") as f:
            return f.read()

    def resolved_lockfile(self) -> CoursierResolvedLockfile:
        lockfile_content = self.lockfile_content()
        lockfile_content_json = json.loads(lockfile_content)
        return CoursierResolvedLockfile.from_json_dict(lockfile_content_json)


@union
class JvmToolLockfileSentinel:
    options_scope: ClassVar[str]


@dataclass(frozen=True)
class JvmToolLockfileRequest:
    artifacts: FrozenOrderedSet[Coordinate]
    resolve_name: str
    lockfile_dest: str

    @classmethod
    def from_tool(cls, tool: JvmToolBase) -> JvmToolLockfileRequest:
        return cls(
            artifacts=FrozenOrderedSet((*tool.artifacts, *tool.extra_artifacts)),
            resolve_name=tool.options_scope,
            lockfile_dest=tool.lockfile,
        )


@dataclass(frozen=True)
class JvmToolLockfile:
    digest: Digest
    resolve_name: str
    path: str


class GenerateJvmLockfilesSubsystem(GoalSubsystem):
    name = "jvm-generate-lockfiles"
    help = "Generate lockfiles for JVM tools third-party dependencies."
    required_union_implementations = (JvmToolLockfileSentinel,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--resolve",
            type=list,
            member_type=str,
            advanced=False,
            help=(
                "Only generate lockfiles for the specified resolve(s).\n\n"
                "Resolves are the logical names for tool lockfiles which are "
                "the options scope for that tool such as `junit-tool`.\n\n"
                "For example, you can run `./pants generate-lockfiles --resolve=junit-tool "
                "to only generate lockfiles for that tool.\n\n"
                "If you specify an invalid resolve name, like 'fake', Pants will output all "
                "possible values.\n\n"
                "If not specified, Pants will generate lockfiles for all resolves."
            ),
        )

    @property
    def resolve_names(self) -> tuple[str, ...]:
        return tuple(self.options.resolve)


class GenerateJvmLockfilesGoal(Goal):
    subsystem_cls = GenerateJvmLockfilesSubsystem


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace,
    union_membership: UnionMembership,
    generate_lockfiles_subsystem: GenerateJvmLockfilesSubsystem,
) -> GenerateJvmLockfilesGoal:
    specified_tool_sentinels = determine_resolves_to_generate(
        union_membership[JvmToolLockfileSentinel],
        generate_lockfiles_subsystem.resolve_names,
    )

    specified_tool_requests = await MultiGet(
        Get(JvmToolLockfileRequest, JvmToolLockfileSentinel, sentinel())
        for sentinel in specified_tool_sentinels
    )

    applicable_tool_requests = filter_tool_lockfile_requests(
        specified_tool_requests,
        resolve_specified=bool(generate_lockfiles_subsystem.resolve_names),
    )

    results = await MultiGet(
        Get(JvmToolLockfile, JvmToolLockfileRequest, req) for req in applicable_tool_requests
    )

    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile for the resolve `{result.resolve_name}` to {result.path}")

    return GenerateJvmLockfilesGoal(exit_code=0)


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: JvmToolLockfileRequest,
) -> JvmToolLockfile:
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements(request.artifacts))
    lockfile_content = resolved_lockfile.to_json()
    lockfile_digest = await Get(
        Digest, CreateDigest([FileContent(request.lockfile_dest, lockfile_content)])
    )
    return JvmToolLockfile(lockfile_digest, request.resolve_name, request.lockfile_dest)


def determine_resolves_to_generate(
    all_tool_sentinels: Iterable[type[JvmToolLockfileSentinel]],
    requested_resolve_names: Sequence[str],
) -> list[type[JvmToolLockfileSentinel]]:
    """Apply the `--resolve` option to determine which resolves are specified.

    Return the tool_lockfile_sentinels to operate on.
    """
    resolve_names_to_sentinels = {
        sentinel.options_scope: sentinel for sentinel in all_tool_sentinels
    }

    if not requested_resolve_names:
        return list(all_tool_sentinels)

    specified_sentinels = []
    unrecognized_resolve_names = []
    for resolve_name in requested_resolve_names:
        sentinel = resolve_names_to_sentinels.get(resolve_name)
        if sentinel:
            specified_sentinels.append(sentinel)
        else:
            unrecognized_resolve_names.append(resolve_name)

    if unrecognized_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names,
            set(resolve_names_to_sentinels.keys()),
            description_of_origin="the option `--jvm-generate-lockfiles-resolve`",
        )

    return specified_sentinels


def filter_tool_lockfile_requests(
    specified_requests: Sequence[JvmToolLockfileRequest], *, resolve_specified: bool
) -> list[JvmToolLockfileRequest]:
    result = []
    for req in specified_requests:
        if req.lockfile_dest not in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE):
            result.append(req)
            continue
        if resolve_specified:
            resolve = req.resolve_name
            raise ValueError(
                f"You requested to generate a lockfile for {resolve} because "
                "you included it in `--jvm-generate-lockfiles-resolve`, but "
                f"`[{resolve}].lockfile` is set to `{req.lockfile_dest}` "
                "so a lockfile will not be generated.\n\n"
                f"If you would like to generate a lockfile for {resolve}, please "
                f"set `[{resolve}].lockfile` to the path where it should be "
                "generated and run again."
            )

    return result


def rules():
    return collect_rules()
