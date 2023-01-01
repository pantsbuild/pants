# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.addresses import UnparsedAddressInputs
from pants.option.option_types import TargetListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class ScroogeJavaSubsystem(Subsystem):
    options_scope = "java-scrooge"
    help = "Java-specific options for the Scrooge Thrift IDL compiler (https://twitter.github.io/scrooge/)."

    _runtime_dependencies = TargetListOption(
        help=softwrap(
            """
            A list of addresses to `jvm_artifact` targets for the runtime
            dependencies needed for generated Java code to work. For example,
            `['3rdparty/jvm:libthrift']`. These dependencies will
            be automatically added to every `thrift_source` target. At the very least,
            this option must be set to a `jvm_artifact` for the
            `org.apache.thrift:libthrift` runtime library.
            """
        ),
    )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(
            self._runtime_dependencies,
            owning_address=None,
            description_of_origin=f"the option `[{self.options_scope}].runtime_dependencies`",
        )
