# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import collect_rules
from pants.option.option_types import StrListOption, TargetListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class ApacheThriftJavaSubsystem(Subsystem):
    options_scope = "java-thrift"
    help = "Options specific to generating Java from Thrift using the Apache Thrift generator"

    gen_options = StrListOption(
        "--options",
        help=softwrap(
            """
            Code generation options specific to the Java code generator to pass to the
            Apache `thrift` binary via the `-gen java` argument.
            See `thrift -help` for supported values.
            """
        ),
    )
    _runtime_dependencies = TargetListOption(
        "--runtime-dependencies",
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
        return UnparsedAddressInputs(self._runtime_dependencies, owning_address=None)


def rules():
    return collect_rules()
