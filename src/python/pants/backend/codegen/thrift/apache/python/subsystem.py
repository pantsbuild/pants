# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption, StrListOption
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
    infer_runtime_dependency = BoolOption(
        "--infer-runtime-dependency",
        default=True,
        help=(
            "If True, will add a dependency on a `python_requirement` target exposing the `thrift` "
            "module (usually from the `thrift` requirement).\n\n"
            "Unless this option is disabled, will error if no relevant target is found or if >2 "
            "is found which causes ambiguity."
        ),
    ).advanced()


def rules():
    return collect_rules()
