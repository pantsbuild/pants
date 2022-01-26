# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.custom_types import target_option
from pants.util.docutil import git_url


class AvroSubsystem(JvmToolBase):
    options_scope = "java-avro"
    help = "Avro IDL compiler (https://avro.apache.org/)."

    default_version = "1.11.0"
    default_artifacts = ("org.apache.avro:avro-tools:{version}",)
    default_lockfile_resource = (
        "pants.backend.codegen.avro.java",
        "avro-tools.default.lockfile.txt",
    )
    default_lockfile_path = (
        "src/python/pants/backend/codegen/avro/java/avro-tools.default.lockfile.txt"
    )
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--runtime-dependencies",
            type=list,
            member_type=target_option,
            help=(
                "A list of addresses to `jvm_artifact` targets for the runtime "
                "dependencies needed for generated Java code to work. For example, "
                "`['3rdparty/jvm:avro-runtime']`. These dependencies will "
                "be automatically added to every `avro_sources` target. At the very least, "
                "this option must be set to a `jvm_artifact` for the "
                f"`org.apache.avro:avro:{cls.default_version}` runtime library."
            ),
        )
