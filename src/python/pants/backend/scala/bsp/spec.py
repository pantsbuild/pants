# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import BuildTargetIdentifier, Uri
from pants.jvm.bsp.spec import JvmBuildTarget

# -----------------------------------------------------------------------------------------------
# Scala-specific Build Target
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scala-build-target
# -----------------------------------------------------------------------------------------------


class ScalaPlatform:
    JVM = 1
    JS = 2
    Native = 3


@dataclass(frozen=True)
class ScalaBuildTarget:
    # The Scala organization that is used for a target.
    scala_organization: str

    # The scala version to compile this target
    scala_version: str

    # The binary version of scalaVersion.
    # For example, 2.12 if scalaVersion is 2.12.4.
    scala_binary_version: str

    # The target platform for this target.
    # See `ScalaPlatform` constants.
    platform: int

    # A sequence of Scala jars such as scala-library, scala-compiler and scala-reflect.
    jars: tuple[str, ...]

    # The jvm build target describing jdk to be used
    jvm_build_target: JvmBuildTarget | None = None

    @classmethod
    def from_json_dict(cls, d: Any):
        return cls(
            scala_organization=d["scalaOrganization"],
            scala_version=d["scalaVersion"],
            scala_binary_version=d["scalaBinaryVersion"],
            platform=d["platform"],
            jars=tuple(d.get("jars", [])),
            jvm_build_target=JvmBuildTarget.from_json_dict(d["jvmBuildTarget"])
            if "jvmBuildTarget" in d
            else None,
        )

    def to_json_dict(self):
        result = {
            "scalaOrganization": self.scala_organization,
            "scalaVersion": self.scala_version,
            "scalaBinaryVersion": self.scala_binary_version,
            "platform": self.platform,
            "jars": list(self.jars),
        }
        if self.jvm_build_target is not None:
            result["jvmBuildTarget"] = self.jvm_build_target.to_json_dict()
        return result


# -----------------------------------------------------------------------------------------------
# Scalac Options Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scalac-options-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalacOptionsParams:
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
class ScalacOptionsItem:
    target: BuildTargetIdentifier

    # Additional arguments to the compiler.
    # For example, -deprecation.
    options: tuple[str, ...]

    # The dependency classpath for this target, must be
    # identical to what is passed as arguments to
    # the -classpath flag in the command line interface
    # of scalac.
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
class ScalacOptionsResult:
    items: tuple[ScalacOptionsItem, ...]

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}
