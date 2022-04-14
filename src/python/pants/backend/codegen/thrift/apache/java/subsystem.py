# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.rules import collect_rules
from pants.option.option_types import StrListOption
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


def rules():
    return collect_rules()
