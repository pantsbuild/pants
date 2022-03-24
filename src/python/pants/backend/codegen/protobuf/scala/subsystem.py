# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import StrListOption
from pants.util.docutil import git_url
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PluginArtifactSpec:
    name: str
    artifact: str

    @classmethod
    def from_str(cls, s):
        name, _, artifact = s.partition("=")
        if name == "" or artifact == "":
            # TODO: Improve error message.
            raise ValueError(f"Plugin artifact `{s}` could not be parsed.")
        return cls(
            name=name,
            artifact=artifact,
        )


class ScalaPBSubsystem(JvmToolBase):
    options_scope = "scalapb"
    help = "The ScalaPB protocol buffer compiler (https://scalapb.github.io/)."

    default_version = "0.11.6"
    default_artifacts = ("com.thesamet.scalapb:scalapbc_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.protobuf.scala",
        "scalapbc.default.lockfile.txt",
    )
    default_lockfile_path = (
        "src/python/pants/backend/codegen/protobuf/scala/scalapbc.default.lockfile.txt"
    )
    default_lockfile_url = git_url(default_lockfile_path)

    _jvm_plugins = StrListOption(
        "--jvm-plugins",
        help=softwrap(
            """
            A list of JVM-based `protoc` plugins to invoke when generating Scala code from protobuf files.
            The format for each plugin specifier is `NAME=ARTIFACT` where NAME is the name of the
            plugin and ARTIFACT is either the address of a `jvm_artifact` target or the colon-separated
            Maven coordinate for the plugin's jar artifact.

            For example, to invoke the fs2-grpc protoc plugin, the following option would work:
            `--scalapb-jvm-plugins=fs2=org.typelevel:fs2-grpc-codegen_2.12:2.3.1`.
            (Note: you would also need to set --scalapb-runtime-dependencies appropriately
            to include the applicable runtime libraries for your chosen protoc plugins.)
            """
        ),
    )

    @property
    def jvm_plugins(self) -> tuple[PluginArtifactSpec, ...]:
        return tuple(PluginArtifactSpec.from_str(pa_str) for pa_str in self._jvm_plugins)
