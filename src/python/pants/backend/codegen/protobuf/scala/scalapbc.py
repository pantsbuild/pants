# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.docutil import git_url


class ScalaPBSubsystem(JvmToolBase):
    options_scope = "scalapb"
    help = "The ScalaPB protocol buffer compiler (https://scalapb.github.io/)."

    default_version = "0.11.6"
    default_artifacts = ("com.thesamet.scalapb:scalapbc_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.protobuf.scala",
        "scalapbc.default.lockfile.txt",
    )
    default_lockfile_url = git_url(
        "src/python/pants/backend/codegen/protobuf/scala/scalapbc.default.lockfile.txt"
    )
