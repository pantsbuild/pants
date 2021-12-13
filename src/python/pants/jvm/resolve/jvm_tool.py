# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import importlib.resources
import json
import logging
from dataclasses import dataclass
from typing import ClassVar, Iterable, Sequence, cast

from pants.backend.python.target_types import UnrecognizedResolveNamesError
from pants.build_graph.address import Address, AddressInput
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmArtifactFieldSet
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

DEFAULT_TOOL_LOCKFILE = "<default>"


logger = logging.getLogger(__name__)


class JvmToolBase(Subsystem):
    """Base class for subsystems that configure a set of artifact requirements for a JVM tool."""

    # Default version of the tool. (Subclasses may set.)
    default_version: ClassVar[str | None] = None

    # Default artifacts for the tool in GROUP:NAME format. The `--version` value will be used for the
    # artifact version if it has not been specified for a particular requirement. (Subclasses must set.)
    default_artifacts: ClassVar[tuple[str, ...]]

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
                "Version string for the tool. This is available for substitution in the "
                f"`[{cls.options_scope}].artifacts` option by including the string "
                "`{version}`."
            ),
        )
        register(
            "--artifacts",
            type=list,
            member_type=str,
            advanced=True,
            default=list(cls.default_artifacts),
            help=(
                "Artifact requirements for this tool using specified as either the address of a `jvm_artifact` "
                "target or, alternatively, as a colon-separated Maven coordinates (e.g., group:name:version). "
                "For Maven coordinates, the string `{version}` version will be substituted with the value of the "
                f"`[{cls.options_scope}].version` option."
            ),
        )
        register(
            "--lockfile",
            type=str,
            default=DEFAULT_TOOL_LOCKFILE,
            advanced=True,
            help=(
                "Path to a lockfile used for installing the tool.\n\n"
                f"Set to the string `{DEFAULT_TOOL_LOCKFILE}` to use a lockfile provided by "
                "Pants, so long as you have not changed the `--version` option. "
                f"See {cls.default_lockfile_url} for the default lockfile contents.\n\n"
                "To use a custom lockfile, set this option to a file path relative to the "
                f"build root, then run `./pants jvm-generate-lockfiles "
                f"--resolve={cls.options_scope}`.\n\n"
            ),
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def artifact_inputs(self) -> tuple[str, ...]:
        return tuple(s.format(version=self.version) for s in self.options.artifacts)

    @property
    def lockfile(self) -> str:
        f"""The path to a lockfile or special string '{DEFAULT_TOOL_LOCKFILE}'."""
        lockfile = cast(str, self.options.lockfile)
        return lockfile

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
    artifact_inputs: FrozenOrderedSet[str]
    resolve_name: str
    lockfile_dest: str

    @classmethod
    def from_tool(cls, tool: JvmToolBase) -> JvmToolLockfileRequest:
        lockfile_dest = tool.lockfile
        if lockfile_dest == DEFAULT_TOOL_LOCKFILE:
            raise ValueError(
                f"Internal error: Request to write tool lockfile but `[{tool.options_scope}.lockfile]` "
                f'is set to the default ("{DEFAULT_TOOL_LOCKFILE}").'
            )
        return cls(
            artifact_inputs=FrozenOrderedSet(tool.artifact_inputs),
            resolve_name=tool.options_scope,
            lockfile_dest=tool.lockfile,
        )


@dataclass(frozen=True)
class JvmToolLockfile:
    digest: Digest
    resolve_name: str
    path: str


@dataclass(frozen=True)
class GatherJvmCoordinatesRequest:
    artifact_inputs: FrozenOrderedSet[str]
    option_name: str


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
                "the options scope for that tool such as `junit`.\n\n"
                "For example, you can run `./pants jvm-generate-lockfiles --resolve=junit "
                "to only generate lockfiles for the `junit` tool.\n\n"
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


@rule
async def gather_coordinates_for_jvm_lockfile(
    request: GatherJvmCoordinatesRequest,
) -> ArtifactRequirements:
    # Separate `artifact_inputs` by whether the strings parse as an `Address` or not.
    requirements: set[ArtifactRequirement] = set()
    candidate_address_inputs: set[AddressInput] = set()
    bad_artifact_inputs = []
    for artifact_input in request.artifact_inputs:
        # Try parsing as a `Coordinate` first since otherwise `AddressInput.parse` will try to see if the
        # group name is a file on disk.
        if 2 <= artifact_input.count(":") <= 3:
            try:
                maybe_coord = Coordinate.from_coord_str(artifact_input).as_requirement()
                requirements.add(maybe_coord)
                continue
            except Exception:
                pass

        try:
            address_input = AddressInput.parse(artifact_input)
            candidate_address_inputs.add(address_input)
        except Exception:
            bad_artifact_inputs.append(artifact_input)

    if bad_artifact_inputs:
        raise ValueError(
            "The following values could not be parsed as an address nor as a JVM coordinate string. "
            f"The problematic inputs supplied to the `{request.option_name}` option were: "
            f"{', '.join(bad_artifact_inputs)}."
        )

    # Gather coordinates from the provided addresses.
    addresses = await MultiGet(Get(Address, AddressInput, ai) for ai in candidate_address_inputs)
    all_supplied_targets = await Get(Targets, Addresses(addresses))
    other_targets = []
    for tgt in all_supplied_targets:
        if JvmArtifactFieldSet.is_applicable(tgt):
            requirements.add(ArtifactRequirement.from_jvm_artifact_target(tgt))
        else:
            other_targets.append(tgt)

    if other_targets:
        raise ValueError(
            "The following addresses reference targets that are not `jvm_artifact` targets. "
            f"Please only supply the addresses of `jvm_artifact` for the `{request.option_name}` "
            f"option. The problematic addresses are: {', '.join(str(tgt.address) for tgt in other_targets)}."
        )

    return ArtifactRequirements(requirements)


@rule
async def load_jvm_lockfile(
    request: JvmToolLockfileRequest,
) -> CoursierResolvedLockfile:
    """Loads an existing lockfile."""

    if not request.artifact_inputs:
        return CoursierResolvedLockfile(entries=())

    lockfile_snapshot = await Get(Snapshot, PathGlobs([request.lockfile_dest]))
    if not lockfile_snapshot.files:
        raise ValueError(
            f"JVM tool `{request.resolve_name}` does not have a lockfile generated. "
            f"Run `{GenerateJvmLockfilesSubsystem.name} --resolve={request.resolve_name} to "
            "generate it."
        )

    return await Get(
        CoursierResolvedLockfile,
        CoursierResolveKey(
            name=request.resolve_name, path=request.lockfile_dest, digest=lockfile_snapshot.digest
        ),
    )


@rule(desc="Generate JVM lockfile", level=LogLevel.DEBUG)
async def generate_jvm_lockfile(
    request: JvmToolLockfileRequest,
) -> JvmToolLockfile:
    requirements = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(request.artifact_inputs, f"[{request.resolve_name}].artifacts"),
    )
    resolved_lockfile = await Get(CoursierResolvedLockfile, ArtifactRequirements, requirements)
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
        if req.lockfile_dest != DEFAULT_TOOL_LOCKFILE:
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
