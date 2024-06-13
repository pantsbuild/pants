# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import Uri
from pants.bsp.utils import freeze_json


@dataclass(frozen=True)
class BuildClientCapabilities:
    # The languages that this client supports.
    # The ID strings for each language are defined in the LSP.
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
            data=freeze_json(d.get("data")),
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

    # The server can provide a list of dependency modules (libraries with meta information)
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
            compile_provider=(
                CompileProvider.from_json_dict(d["compileProvider"])
                if "compileProvider" in d
                else None
            ),
            test_provider=(
                TestProvider.from_json_dict(d["testProvider"]) if "testProvider" in d else None
            ),
            run_provider=(
                RunProvider.from_json_dict(d["runProvider"]) if "runProvider" in d else None
            ),
            debug_provider=(
                DebugProvider.from_json_dict(d["debugProvider"]) if "debugProvider" in d else None
            ),
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
