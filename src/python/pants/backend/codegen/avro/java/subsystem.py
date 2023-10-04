# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm.resolve.jvm_tool import JvmToolBase


class AvroSubsystem(JvmToolBase):
    options_scope = "java-avro"
    help = "Avro IDL compiler (https://avro.apache.org/)."

    default_version = "1.11.0"
    default_artifacts = ("org.apache.avro:avro-tools:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.avro.java",
        "avro-tools.default.lockfile.txt",
    )
