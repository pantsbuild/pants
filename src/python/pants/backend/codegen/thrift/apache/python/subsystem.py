# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.rules import collect_rules
from pants.option.option_types import StrListOption, TargetListOption
from pants.option.subsystem import Subsystem


class ThriftPythonSubsystem(Subsystem):
    options_scope = "python-thrift"
    help = "Options specific to generating Python from Thrift using Apache Thrift"

    gen_options = StrListOption(
        "--options",
        help=(
            "Code generation options specific to the Python code generator to pass to the "
            "Apache `thift` binary via the `-gen py` argument. "
            "See `thrift -help` for supported values."
        ),
    )
    _runtime_dependencies = TargetListOption(
        "--runtime-dependencies",
        help=(
            "A list of addresses to `python_requirement` targets for the runtime "
            "dependencies needed for generated Python code to work. For example, "
            "`['3rdparty/python:thrift']`. These dependencies will "
            "be automatically added to every `thrift_source` target. At the very least, "
            "this option must be set to a `python_requirement` for the "
            "`thrift` runtime library."
        ),
    )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self._runtime_dependencies, owning_address=None)


def rules():
    return collect_rules()
