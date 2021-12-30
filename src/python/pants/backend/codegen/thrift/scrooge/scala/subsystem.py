# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.engine.addresses import UnparsedAddressInputs
from pants.option.custom_types import target_option
from pants.option.subsystem import Subsystem


class ScroogeScalaSubsystem(Subsystem):
    options_scope = "scrooge-scala"
    help = "Scala-specific options for the Scrooge Thrift IDL compiler (https://twitter.github.io/scrooge/)."

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
                "`['3rdparty/jvm:scrooge-runtime']`. These dependencies will "
                "be automatically added to every `thrift_source` target. At the very least, "
                "this option must be set to a `jvm_artifact` for the "
                f"`com.twitter:scrooge-runtime_SCALAVER:{ScroogeSubsystem.default_version}` runtime library."
            ),
        )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.runtime_dependencies, owning_address=None)
