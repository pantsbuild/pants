# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.bsp.spec.base import BuildTargetIdentifier, Uri

# -----------------------------------------------------------------------------------------------
# Javac Options Request
# See https://build-server-protocol.github.io/docs/extensions/java.html#javac-options-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JavacOptionsParams:
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
class JavacOptionsItem:
    target: BuildTargetIdentifier

    # Additional arguments to the compiler.
    # For example, -deprecation.
    options: tuple[str, ...]

    # The dependency classpath for this target, must be
    # identical to what is passed as arguments to
    # the -classpath flag in the command line interface
    # of javac.
    classpath: tuple[Uri, ...]

    # The output directory for classfiles produced by this target
    class_directory: Uri

    def to_json_dict(self):
        return {
            "target": self.target.to_json_dict(),
            "options": self.options,
            "classpath": self.classpath,
            "classDirectory": self.class_directory,
        }


@dataclass(frozen=True)
class JavacOptionsResult:
    items: tuple[JavacOptionsItem, ...]

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}
