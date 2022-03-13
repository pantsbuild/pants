# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import BSPData, Uri


@dataclass(frozen=True)
class JvmBuildTarget:
    # Uri representing absolute path to jdk
    # For example: file:///usr/lib/jvm/java-8-openjdk-amd64
    java_home: Uri | None = None

    # The java version this target is supposed to use.
    # For example: 1.8
    java_version: str | None = None

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        return cls(
            java_home=d.get("javaHome"),
            java_version=d.get("javaVersion"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        result = {}
        if self.java_home is not None:
            result["javaHome"] = self.java_home
        if self.java_version is not None:
            result["javaVersion"] = self.java_version
        return result


@dataclass(frozen=True)
class MavenDependencyModuleArtifact:
    uri: Uri
    classifier: str | None = None

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        return cls(uri=d["uri"], classifier=d.get("classifier"))

    def to_json_dict(self) -> Any:
        result = {"uri": self.uri}
        if self.classifier is not None:
            result["classifier"] = self.classifier
        return result


@dataclass(frozen=True)
class MavenDependencyModule(BSPData):
    """Maven-related module metadata."""

    organization: str
    name: str
    version: str
    scope: str | None
    artifacts: tuple[MavenDependencyModuleArtifact, ...]

    DATA_KIND = "maven"

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        return cls(
            organization=d["organization"],
            name=d["name"],
            version=d["version"],
            scope=d.get("scope"),
            artifacts=tuple(
                MavenDependencyModuleArtifact.from_json_dict(ma) for ma in d.get("artifacts", [])
            ),
        )

    def to_json_dict(self) -> Any:
        result = {
            "organization": self.organization,
            "name": self.name,
            "version": self.version,
            "artifacts": [ma.to_json_dict() for ma in self.artifacts],
        }
        if self.scope is not None:
            result["scope"] = self.scope
        return result
