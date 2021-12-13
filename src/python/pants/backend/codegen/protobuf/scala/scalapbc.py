# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.addresses import UnparsedAddressInputs
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.custom_types import target_option
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

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--runtime-dependencies",
            type=list,
            member_type=target_option,
            help=(
                "A list of addresses to `jvm_artifact` targets for the runtime "
                "dependencies needed for generated Scala code to work. For example, "
                "`['3rdparty/jvm:scalapb-runtime']`. These dependencies will "
                "be automatically added to every `protobuf_sources` target. At the very leasst, "
                "this option must be set to a `jvm_artifact` for the "
                f"`com.thesamet.scalapb:scalapb-runtime_SCALAVER:{cls.default_version}` runtime library."
            ),
        )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.runtime_dependencies, owning_address=None)
