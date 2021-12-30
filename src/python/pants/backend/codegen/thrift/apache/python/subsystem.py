# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import cast

from pants.engine.rules import collect_rules
from pants.option.subsystem import Subsystem


class ThriftPythonSubsystem(Subsystem):
    options_scope = "thrift-python"
    help = "Options specific to generating Python from Thrift using Apache Thrift"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--options",
            type=list,
            member_type=str,
            help=(
                "Code generation options specific to the Python code generator to pass to the "
                "Apache `thift` binary via the `-gen py` argument. "
                "See `thrift -help` for supported values."
            ),
        )

    @property
    def gen_options(self) -> tuple[str, ...]:
        return cast("tuple[str, ...]", tuple(self.options.options))


def rules():
    return collect_rules()
