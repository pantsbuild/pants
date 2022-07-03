# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class ThriftPythonSubsystem(Subsystem):
    options_scope = "python-thrift"
    help = "Options specific to generating Python from Thrift using Apache Thrift"

    gen_options = StrListOption(
        "--options",
        help=softwrap(
            """
            Code generation options specific to the Python code generator to pass to the
            Apache `thift` binary via the `-gen py` argument.
            See `thrift -help` for supported values.
            """
        ),
    )
    infer_runtime_dependency = BoolOption(
        default=True,
        help=softwrap(
            """
            If True, will add a dependency on a `python_requirement` target exposing the `thrift`
            module (usually from the `thrift` requirement).

            If `[python].enable_resolves` is set, Pants will only infer dependencies on
            `python_requirement` targets that use the same resolve as the particular
            `thrift_source` / `thrift_source` target uses, which is set via its
            `python_resolve` field.

            Unless this option is disabled, Pants will error if no relevant target is found or
            more than one is found which causes ambiguity.
            """
        ),
        advanced=True,
    )


def rules():
    return collect_rules()
