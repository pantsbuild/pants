# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

from pants.build_graph.address import Address, AddressInput
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Targets
from pants.jvm.goals import lockfile
from pants.jvm.goals.lockfile import GenerateJvmLockfile
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    GatherJvmCoordinatesRequest,
)
from pants.jvm.target_types import JvmArtifactFieldSet
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet


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
        return cast(str, self.options.lockfile)


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


@dataclass(frozen=True)
class GenerateJvmLockfileFromTool:
    """Create a `GenerateJvmLockfile` request for a JVM tool.

    We allow tools to either use coordinates or addresses to `jvm_artifact` targets for the artifact
    inputs. This is a convenience to parse those artifact inputs to create a standardized
    `GenerateJvmLockfile`.
    """

    artifact_inputs: FrozenOrderedSet[str]
    artifact_option_name: str
    lockfile_option_name: str
    resolve_name: str
    lockfile_dest: str
    default_lockfile_resource: tuple[str, str]

    @classmethod
    def create(cls, tool: JvmToolBase) -> GenerateJvmLockfileFromTool:
        return GenerateJvmLockfileFromTool(
            FrozenOrderedSet(tool.artifact_inputs),
            artifact_option_name=f"[{tool.options_scope}].artifacts",
            lockfile_option_name=f"[{tool.options_scope}].lockfile",
            resolve_name=tool.options_scope,
            lockfile_dest=tool.lockfile,
            default_lockfile_resource=tool.default_lockfile_resource,
        )


@rule
async def setup_lockfile_request_from_tool(
    request: GenerateJvmLockfileFromTool,
) -> GenerateJvmLockfile:
    artifacts = await Get(
        ArtifactRequirements,
        GatherJvmCoordinatesRequest(request.artifact_inputs, request.artifact_option_name),
    )
    return GenerateJvmLockfile(
        artifacts=artifacts, resolve_name=request.resolve_name, lockfile_dest=request.lockfile_dest
    )


def rules():
    return (*collect_rules(), *lockfile.rules())
