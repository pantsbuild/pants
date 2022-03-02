# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from pants.bsp.spec.base import BuildTarget, BuildTargetIdentifier, Uri

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

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}
