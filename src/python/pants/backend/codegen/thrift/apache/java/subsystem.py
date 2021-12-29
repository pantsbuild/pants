# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import cast

from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import collect_rules
from pants.option.custom_types import target_option
from pants.option.subsystem import Subsystem


class ApacheThriftJavaSubsystem(Subsystem):
    options_scope = "apache-thrift-java"
    help = "Options specific to generating Java from Thrift using the Apache Thrift generator"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--options",
            type=list,
            member_type=str,
            help=(
                "Code generation options specific to the Java code generator to pass to the "
                "Apache `thrift` binary via the `-gen java` argument. "
                "See `thrift -help` for supported values."
            ),
        )
        register(
            "--runtime-dependencies",
            type=list,
            member_type=target_option,
            help=(
                "A list of addresses to `jvm_artifact` targets for the runtime "
                "dependencies needed for generated Java code to work. For example, "
                "`['3rdparty/jvm:libthrift']`. These dependencies will "
                "be automatically added to every `thrift_source` target. At the very least, "
                "this option must be set to a `jvm_artifact` for the "
                "`org.apache.thrift:libthrift` runtime library."
            ),
        )

    @property
    def gen_options(self) -> tuple[str, ...]:
        return cast("tuple[str, ...]", tuple(self.options.options))

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.runtime_dependencies, owning_address=None)


def rules():
    return collect_rules()
