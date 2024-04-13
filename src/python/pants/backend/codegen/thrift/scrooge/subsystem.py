# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.jvm.resolve.jvm_tool import JvmToolBase


class ScroogeSubsystem(JvmToolBase):
    options_scope = "scrooge"
    help = "The Scrooge Thrift IDL compiler (https://twitter.github.io/scrooge/)."

    default_version = "21.12.0"
    default_artifacts = ("com.twitter:scrooge-generator_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.thrift.scrooge",
        "scrooge.default.lockfile.txt",
    )
