# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from pants.bsp.spec.base import BSPData, BuildTarget, BuildTargetIdentifier, Uri

# -----------------------------------------------------------------------------------------------
# Workspace Build Targets Request
# See https://build-server-protocol.github.io/docs/specification.html#workspace-build-targets-request
# -----------------------------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------------------------
# Build Target Sources Request
# See https://build-server-protocol.github.io/docs/specification.html#build-target-sources-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourcesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
        )

    def to_json_dict(self):
        return {
            "targets": [tgt.to_json_dict() for tgt in self.targets],
        }


class SourceItemKind(IntEnum):
    FILE = 1
    DIRECTORY = 2


@dataclass(frozen=True)
class SourceItem:
    uri: Uri
    kind: SourceItemKind
    generated: bool = False

    @classmethod
    def from_json_dict(cls, d: Any):
        return cls(
            uri=d["uri"],
            kind=SourceItemKind(d["kind"]),
            generated=d["generated"],
        )

    def to_json_dict(self):
        return {
            "uri": self.uri,
            "kind": self.kind.value,
            "generated": self.generated,
        }


@dataclass(frozen=True)
class SourcesItem:
    target: BuildTargetIdentifier
    sources: tuple[SourceItem, ...]
    roots: tuple[Uri, ...] | None

    @classmethod
    def from_json_dict(cls, d: Any):
        return cls(
            target=BuildTargetIdentifier.from_json_dict(d["target"]),
            sources=tuple(SourceItem.from_json_dict(i) for i in d["sources"]),
            roots=tuple(d.get("sources", ())),
        )

    def to_json_dict(self):
        result = {
            "target": self.target.to_json_dict(),
            "sources": [src.to_json_dict() for src in self.sources],
        }
        if self.roots is not None:
            result["roots"] = list(self.roots)
        return result


@dataclass(frozen=True)
class SourcesResult:
    items: tuple[SourcesItem, ...]

    @classmethod
    def from_json_dict(cls, d: Any):
        return cls(
            items=tuple(SourcesItem.from_json_dict(i) for i in d["items"]),
        )

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}


# -----------------------------------------------------------------------------------------------
# Dependency Sources Request
# See https://build-server-protocol.github.io/docs/specification.html#dependency-sources-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencySourcesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
        )

    def to_json_dict(self):
        return {
            "targets": [tgt.to_json_dict() for tgt in self.targets],
        }


@dataclass(frozen=True)
class DependencySourcesItem:
    target: BuildTargetIdentifier
    # List of resources containing source files of the
    # target's dependencies.
    # Can be source files, jar files, zip files, or directories.
    sources: tuple[Uri, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json_dict(),
            "sources": self.sources,
        }


@dataclass(frozen=True)
class DependencySourcesResult:
    items: tuple[DependencySourcesItem, ...]

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}


# -----------------------------------------------------------------------------------------------
# Dependency Modules Request
# See https://build-server-protocol.github.io/docs/specification.html#dependency-modules-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencyModulesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
        )

    def to_json_dict(self):
        return {
            "targets": [tgt.to_json_dict() for tgt in self.targets],
        }


@dataclass(frozen=True)
class DependencyModule:
    # Module name
    name: str

    # Module version
    version: str

    # Language-specific metadata about this module.
    # See MavenDependencyModule as an example.
    data: BSPData | None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
        }
        if self.data is not None:
            result["dataKind"] = self.data.DATA_KIND
            result["data"] = self.data.to_json_dict()
        return result


@dataclass(frozen=True)
class DependencyModulesItem:
    target: BuildTargetIdentifier
    modules: tuple[DependencyModule, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json_dict(),
            "modules": [m.to_json_dict() for m in self.modules],
        }


@dataclass(frozen=True)
class DependencyModulesResult:
    items: tuple[DependencyModulesItem, ...]

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}
