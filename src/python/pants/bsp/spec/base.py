# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, ClassVar

from pants.build_graph.address import Address

# -----------------------------------------------------------------------------------------------
# Basic JSON Structures
# See https://build-server-protocol.github.io/docs/specification.html#basic-json-structures
# -----------------------------------------------------------------------------------------------

Uri = str


@dataclass(frozen=True)
class BuildTargetIdentifier:
    """A unique identifier for a target, can use any URI-compatible encoding as long as it is unique
    within the workspace.

    Clients should not infer metadata out of the URI structure such as the path or query parameters,
    use BuildTarget instead.
    """

    # The target’s Uri
    uri: Uri

    @classmethod
    def from_json_dict(cls, d):
        return cls(uri=d["uri"])

    def to_json_dict(self):
        return {"uri": self.uri}

    @classmethod
    def from_address(cls, addr: Address) -> BuildTargetIdentifier:
        return cls(uri=f"pants:{str(addr)}")


@dataclass(frozen=True)
class BuildTargetCapabilities:
    # This target can be compiled by the BSP server.
    can_compile: bool = False

    # This target can be tested by the BSP server.
    can_test: bool = False

    # This target can be run by the BSP server.
    can_run: bool = False

    # This target can be debugged by the BSP server.
    can_debug: bool = False

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            can_compile=d["canCompile"],
            can_test=d["canTest"],
            can_run=d["canRun"],
            can_debug=d["canDebug"],
        )

    def to_json_dict(self):
        return {
            "canCompile": self.can_compile,
            "canTest": self.can_test,
            "canRun": self.can_run,
            "canDebug": self.can_debug,
        }


# Note: The BSP "build target" concept is _not_ the same as a Pants "target". They are similar but
# should be not be conflated with one another.
@dataclass(frozen=True)
class BuildTarget:
    """Build target contains metadata about an artifact (for example library, test, or binary
    artifact)"""

    # The target’s unique identifier
    id: BuildTargetIdentifier

    # A human readable name for this target.
    # May be presented in the user interface.
    # Should be unique if possible.
    # The id.uri is used if None.
    display_name: str | None

    # The directory where this target belongs to. Multiple build targets are allowed to map
    # to the same base directory, and a build target is not required to have a base directory.
    # A base directory does not determine the sources of a target, see buildTarget/sources. */
    base_directory: Uri | None

    # Free-form string tags to categorize or label this build target.
    # For example, can be used by the client to:
    # - customize how the target should be translated into the client's project model.
    # - group together different but related targets in the user interface.
    # - display icons or colors in the user interface.
    # Pre-defined tags are listed in `BuildTargetTag` but clients and servers
    # are free to define new tags for custom purposes.
    tags: tuple[str, ...]

    # The capabilities of this build target.
    capabilities: BuildTargetCapabilities

    # The set of languages that this target contains.
    # The ID string for each language is defined in the LSP.
    language_ids: tuple[str, ...]

    # The direct upstream build target dependencies of this build target
    dependencies: tuple[BuildTargetIdentifier, ...]

    # Language-specific metadata about this target.
    # See ScalaBuildTarget as an example.
    data: BSPData | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            id=BuildTargetIdentifier.from_json_dict(d["id"]),
            display_name=d.get("displayName"),
            base_directory=d["baseDirectory"],
            tags=tuple(d.get("tags", [])),
            capabilities=BuildTargetCapabilities.from_json_dict(d["capabilities"]),
            language_ids=tuple(d.get("languageIds", [])),
            dependencies=tuple(
                BuildTargetIdentifier.from_json_dict(x) for x in d.get("dependencies", [])
            ),
            # data_kind=d.get("dataKind"),  # TODO: figure out generic decode, this is only used in tests!
            data=d.get("data"),
        )

    def to_json_dict(self):
        result = {
            "id": self.id.to_json_dict(),
            "capabilities": self.capabilities.to_json_dict(),
            "tags": self.tags,
            "languageIds": self.language_ids,
            "dependencies": [dep.to_json_dict() for dep in self.dependencies],
        }
        if self.display_name is not None:
            result["displayName"] = self.display_name
        if self.base_directory is not None:
            result["baseDirectory"] = self.base_directory
        if self.data is not None:
            result["dataKind"] = self.data.DATA_KIND
            result["data"] = self.data.to_json_dict()
        return result


class BuildTargetDataKind:
    # The `data` field contains a `ScalaBuildTarget` object.
    SCALA = "scala"

    # The `data` field contains a `SbtBuildTarget` object.
    SBT = "sbt"


class BuildTargetTag:
    # Target contains re-usable functionality for downstream targets. May have any
    # combination of capabilities.
    LIBRARY = "library"

    # Target contains source code for producing any kind of application, may have
    # but does not require the `canRun` capability.
    APPLICATION = "application"

    # Target contains source code for testing purposes, may have but does not
    # require the `canTest` capability.
    TEST = "test"

    # Target contains source code for integration testing purposes, may have
    # but does not require the `canTest` capability.
    # The difference between "test" and "integration-test" is that
    # integration tests traditionally run slower compared to normal tests
    # and require more computing resources to execute.
    INTEGRATION_TEST = "integration-test"

    # Target contains source code to measure performance of a program, may have
    # but does not require the `canRun` build target capability.
    BENCHMARK = "benchmark"

    # Target should be ignored by IDEs. */
    NO_IDE = "no-ide"

    # Actions on the target such as build and test should only be invoked manually
    # and explicitly. For example, triggering a build on all targets in the workspace
    # should by default not include this target.
    #
    # The original motivation to add the "manual" tag comes from a similar functionality
    # that exists in Bazel, where targets with this tag have to be specified explicitly
    # on the command line.
    MANUAL = "manual"


@dataclass(frozen=True)
class TaskId:
    """The Task Id allows clients to uniquely identify a BSP task and establish a client-parent
    relationship with another task id."""

    # A unique identifier
    id: str

    # The parent task ids, if any. A non-empty parents field means
    # this task is a sub-task of every parent task id. The child-parent
    # relationship of tasks makes it possible to render tasks in
    # a tree-like user interface or inspect what caused a certain task
    # execution.
    parents: tuple[str, ...] | None = None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            id=d["id"],
            parents=tuple(d["parents"]) if "parents" in d else None,
        )

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
        }
        if self.parents is not None:
            result["parents"] = self.parents
        return result


class StatusCode(IntEnum):
    # Execution was successful.
    OK = 1

    # Execution failed.
    ERROR = 2

    # Execution was cancelled.
    CANCELLED = 3


class BSPData:
    """Mix-in for BSP spec types that can live in a data field."""

    DATA_KIND: ClassVar[str]

    def to_json_dict(self) -> dict[str, Any]:
        raise NotImplementedError
