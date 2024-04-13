# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class ThriftSubsystem(Subsystem):
    options_scope = "thrift"
    help = "General Thrift IDL settings (https://thrift.apache.org/)."

    dependency_inference = BoolOption(
        default=True,
        help="Infer Thrift dependencies on other Thrift files by analyzing import statements.",
    )
    tailor = BoolOption(
        default=True,
        help="If true, add `thrift_sources` targets with the `tailor` goal.",
        advanced=True,
    )
