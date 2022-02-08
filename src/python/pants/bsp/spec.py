# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# -----------------------------------------------------------------------------------------------
# Base types
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


@dataclass(frozen=True)
class BuildTargetCapabilities:
    # This target can be compiled by the BSP server.
    can_compile: bool

    # This target can be tested by the BSP server.
    can_test: bool

    # This target can be run by the BSP server.
    can_run: bool

    # This target can be debugged by the BSP server.
    can_debug: bool

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

    # Kind of data to expect in the `data` field. If this field is not set, the kind of data is not specified.
    data_kind: str | None

    # Language-specific metadata about this target.
    # See ScalaBuildTarget as an example.
    # TODO: Figure out generic decode/encode of this field. Maybe use UnionRule to allow language backends to hook?
    data: Any | None

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
            data_kind=d.get("dataKind"),
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
        if self.data_kind is not None:
            result["dataKind"] = self.data_kind
        if self.data is not None:
            result["data"] = self.data
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
    parents: tuple[str, ...] | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            id=d["id"],
            parents=tuple(d["parents"]) if "parents" in d else None,
        )


class StatusCode:
    # Execution was successful.
    OK = 1

    # Execution failed.
    ERROR = 2

    # Execution was cancelled.
    CANCELLED = 3


# -----------------------------------------------------------------------------------------------
# Protocol types
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildClientCapabilities:
    # The languages that this client supports.
    # The ID strings for each language is defined in the LSP.
    # The server must never respond with build targets for other
    # languages than those that appear in this list.
    language_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(language_ids=tuple(d.get("languageIds", [])))

    def to_json_dict(self):
        return {
            "languageIds": self.language_ids,
        }


@dataclass(frozen=True)
class InitializeBuildParams:
    # Name of the client
    display_name: str

    # The version of the client
    version: str

    # The BSP version that the client speaks
    bsp_version: str

    # The rootUri of the workspace
    root_uri: Uri

    # The capabilities of the client
    capabilities: BuildClientCapabilities

    # Additional metadata about the client
    data: Any | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            display_name=d["displayName"],
            version=d["version"],
            bsp_version=d["bspVersion"],
            root_uri=d["rootUri"],
            capabilities=BuildClientCapabilities.from_json_dict(d["capabilities"]),
            data=d.get("data"),
        )

    def to_json_dict(self):
        result = {
            "displayName": self.display_name,
            "version": self.version,
            "bspVersion": self.bsp_version,
            "rootUri": self.root_uri,
            "capabilities": self.capabilities.to_json_dict(),
        }
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass(frozen=True)
class CompileProvider:
    language_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(language_ids=tuple(d.get("languageIds", [])))

    def to_json_dict(self):
        return {
            "languageIds": self.language_ids,
        }


@dataclass(frozen=True)
class RunProvider:
    language_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(language_ids=tuple(d.get("languageIds", [])))

    def to_json_dict(self):
        return {
            "languageIds": self.language_ids,
        }


@dataclass(frozen=True)
class DebugProvider:
    language_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(language_ids=tuple(d.get("languageIds", [])))

    def to_json_dict(self):
        return {
            "languageIds": self.language_ids,
        }


@dataclass(frozen=True)
class TestProvider:
    language_ids: tuple[str, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(language_ids=tuple(d.get("languageIds", [])))

    def to_json_dict(self):
        return {
            "languageIds": self.language_ids,
        }


@dataclass(frozen=True)
class BuildServerCapabilities:
    # The languages the server supports compilation via method buildTarget/compile.
    compile_provider: CompileProvider | None

    # The languages the server supports test execution via method buildTarget/test
    test_provider: TestProvider | None

    # The languages the server supports run via method buildTarget/run
    run_provider: RunProvider | None

    # The languages the server supports debugging via method debugSession/start
    debug_provider: DebugProvider | None

    # The server can provide a list of targets that contain a
    # single text document via the method buildTarget/inverseSources
    inverse_sources_provider: bool | None

    # The server provides sources for library dependencies
    # via method buildTarget/dependencySources
    dependency_sources_provider: bool | None

    # The server cam provide a list of dependency modules (libraries with meta information)
    # via method buildTarget/dependencyModules
    dependency_modules_provider: bool | None

    # The server provides all the resource dependencies
    # via method buildTarget/resources
    resources_provider: bool | None

    # Reloading the build state through workspace/reload is supported
    can_reload: bool | None

    # The server sends notifications to the client on build
    # target change events via buildTarget/didChange
    build_target_changed_provider: bool | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            compile_provider=CompileProvider.from_json_dict(d["compileProvider"])
            if "compileProvider" in d
            else None,
            test_provider=TestProvider.from_json_dict(d["testProvider"])
            if "testProvider" in d
            else None,
            run_provider=RunProvider.from_json_dict(d["runProvider"])
            if "runProvider" in d
            else None,
            debug_provider=DebugProvider.from_json_dict(d["debugProvider"])
            if "debugProvider" in d
            else None,
            inverse_sources_provider=d.get("inverseSourcesProvider"),
            dependency_sources_provider=d.get("dependencySourcesProvider"),
            dependency_modules_provider=d.get("dependencyModulesProvider"),
            resources_provider=d.get("resourcesProvider"),
            can_reload=d.get("canReload"),
            build_target_changed_provider=d.get("buildTargetChangedProvider"),
        )

    def to_json_dict(self):
        result = {}
        if self.compile_provider is not None:
            result["compileProvider"] = self.compile_provider.to_json_dict()
        if self.test_provider is not None:
            result["testProvider"] = self.test_provider.to_json_dict()
        if self.run_provider is not None:
            result["runProvider"] = self.run_provider.to_json_dict()
        if self.debug_provider is not None:
            result["debugProvider"] = self.debug_provider.to_json_dict()
        if self.inverse_sources_provider is not None:
            result["inverseSourcesProvider"] = self.inverse_sources_provider
        if self.dependency_sources_provider is not None:
            result["dependencySourcesProvider"] = self.dependency_sources_provider
        if self.dependency_modules_provider is not None:
            result["dependencyModulesProvider"] = self.dependency_modules_provider
        if self.resources_provider is not None:
            result["resourcesProvider"] = self.resources_provider
        if self.can_reload is not None:
            result["canReload"] = self.can_reload
        if self.build_target_changed_provider is not None:
            result["buildTargetChangedProvider"] = self.build_target_changed_provider
        return result


@dataclass(frozen=True)
class InitializeBuildResult:
    # Name of the server
    display_name: str

    # The version of the server
    version: str

    # The BSP version that the server speaks
    bsp_version: str

    # The capabilities of the build server
    capabilities: BuildServerCapabilities

    # Additional metadata about the server
    data: Any | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            display_name=d["displayName"],
            version=d["version"],
            bsp_version=d["bspVersion"],
            capabilities=BuildServerCapabilities.from_json_dict(d["capabilities"]),
            data=d.get("data"),
        )

    def to_json_dict(self):
        result = {
            "displayName": self.display_name,
            "version": self.version,
            "bspVersion": self.bsp_version,
            "capabilities": self.capabilities.to_json_dict(),
        }
        if self.data is not None:
            # TODO: Figure out whether to encode/decode data in a generic manner.
            result["data"] = self.data
        return result


@dataclass(frozen=True)
class WorkspaceBuildTargetsParams:
    @classmethod
    def from_json_dict(cls, _d):
        return cls()

    def to_json_dict(self):
        return {}


@dataclass(frozen=True)
class WorkspaceBuildTargetsResult:
    targets: tuple[BuildTarget, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(targets=tuple(BuildTarget.from_json_dict(tgt) for tgt in d["targets"]))

    def to_json_dict(self):
        return {"targets": [tgt.to_json_dict() for tgt in self.targets]}
