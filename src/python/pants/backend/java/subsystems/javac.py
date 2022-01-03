# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import cast

from pants.option.custom_types import shell_str
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class JavacSubsystem(Subsystem):
    options_scope = "javac"
    help = "The javac Java source compiler."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            default=[],
            help=(
                "Global `javac` compiler flags, e.g. "
                f"`--{cls.options_scope}-args='-g -deprecation'`."
            ),
        )

    @property
    def args(self) -> list[str]:
        return cast("list[str]", self.options.args)
