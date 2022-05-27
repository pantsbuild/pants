# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import BSPData, BuildTargetIdentifier, Uri
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
class ScalaBuildTarget(BSPData):
    DATA_KIND = "scala"

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

    def to_json_dict(self) -> dict[str, Any]:
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

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            target=BuildTargetIdentifier.from_json_dict(d["target"]),
            options=tuple(d["options"]),
            classpath=tuple(d["classpath"]),
            class_directory=d["classDirectory"],
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json_dict(),
            "options": self.options,
            "classpath": self.classpath,
            "classDirectory": self.class_directory,
        }


@dataclass(frozen=True)
class ScalacOptionsResult:
    items: tuple[ScalacOptionsItem, ...]

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            items=tuple(ScalacOptionsItem.from_json_dict(x) for x in d["items"]),
        )

    def to_json_dict(self):
        return {"items": [item.to_json_dict() for item in self.items]}


# -----------------------------------------------------------------------------------------------
# Scala Main Classes Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scala-main-classes-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalaMainClassesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    # An optional number uniquely identifying a client request.
    origin_id: str | None = None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
            origin_id=d.get("originId"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "targets": [tgt.to_json_dict() for tgt in self.targets],
        }
        if self.origin_id is not None:
            result["originId"] = self.origin_id
        return result


@dataclass(frozen=True)
class ScalaMainClass:
    # The main class to run.
    class_: str

    # The user arguments to the main entrypoint.
    arguments: tuple[str, ...]

    # The jvm options for the application.
    jvm_options: tuple[str, ...]

    # The environment variables for the application.
    environment_variables: tuple[str, ...] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result = {
            "class": self.class_,
            "arguments": self.arguments,
            "jvmOptions": self.jvm_options,
        }
        if self.environment_variables is not None:
            result["environmentVariables"] = self.environment_variables
        return result


@dataclass(frozen=True)
class ScalaMainClassesItem:
    # The build target that contains the test classes.
    target: BuildTargetIdentifier

    # The main class item.
    classes: tuple[ScalaMainClass, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json_dict(),
            "classes": self.classes,
        }


@dataclass(frozen=True)
class ScalaMainClassesResult:
    items: tuple[ScalaMainClassesItem, ...]

    # An optional id of the request that triggered this result.
    origin_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "items": [item.to_json_dict() for item in self.items],
        }
        if self.origin_id is not None:
            result["originId"] = self.origin_id
        return result


# -----------------------------------------------------------------------------------------------
# Scala Test Classes Request
# See https://build-server-protocol.github.io/docs/extensions/scala.html#scala-test-classes-request
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalaTestClassesParams:
    targets: tuple[BuildTargetIdentifier, ...]

    # An optional number uniquely identifying a client request.
    origin_id: str | None = None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            targets=tuple(BuildTargetIdentifier.from_json_dict(x) for x in d["targets"]),
            origin_id=d.get("originId"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "targets": [tgt.to_json_dict() for tgt in self.targets],
        }
        if self.origin_id is not None:
            result["originId"] = self.origin_id
        return result


@dataclass(frozen=True)
class ScalaTestClassesItem:
    # The build target that contains the test classes.
    target: BuildTargetIdentifier

    # Name of the the framework to which classes belong.
    # It's optional in order to maintain compatibility, however it is expected
    # from the newer implementations to not leave that field unspecified.
    framework: str | None

    # The fully qualified names of the test classes in this target
    classes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "target": self.target.to_json_dict(),
            "classes": self.classes,
        }
        if self.framework is not None:
            result["framework"] = self.framework
        return result


@dataclass(frozen=True)
class ScalaTestClassesResult:
    items: tuple[ScalaTestClassesItem, ...]

    # An optional id of the request that triggered this result.
    origin_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "items": [item.to_json_dict() for item in self.items],
        }
        if self.origin_id is not None:
            result["originId"] = self.origin_id
        return result
