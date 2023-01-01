# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import BuildTargetIdentifier, Uri

# -----------------------------------------------------------------------------------------------
# Resources Request
# See https://build-server-protocol.github.io/docs/specification.html#resources-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourcesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {"targets": [tgt.to_json_dict() for tgt in self.targets]}


@dataclass(frozen=True)
class ResourcesItem:
    target: BuildTargetIdentifier
    # List of resource files.
    resources: tuple[Uri, ...]

    def to_json_dict(self):
        result = {
            "target": self.target.to_json_dict(),
            "resources": self.resources,
        }
        return result


@dataclass(frozen=True)
class ResourcesResult:
    items: tuple[ResourcesItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "items": [ri.to_json_dict() for ri in self.items],
        }
