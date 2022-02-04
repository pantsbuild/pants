# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import cast

from pants.option.subsystem import Subsystem


class ThriftSubsystem(Subsystem):
    options_scope = "thrift"
    help = "General Thrift IDL settings (https://thrift.apache.org/)."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--dependency-inference",
            type=bool,
            default=True,
            help=(
                "Infer Thrift dependencies on other Thrift files by analyzing import statements."
            ),
        )

    @property
    def dependency_inference(self) -> bool:
        return cast(bool, self.options.dependency_inference)
