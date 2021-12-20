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
        register(
            "--jdk",
            default="adopt:1.11",
            advanced=True,
            removal_version="2.10.0.dev0",
            removal_hint="Use `--jvm-jdk`, which behaves the same.",
            help=(
                "The JDK to use for invoking javac.\n\n"
                " This string will be passed directly to Coursier's `--jvm` parameter."
                " Run `cs java --available` to see a list of available JVM versions on your platform.\n\n"
                " If the string 'system' is passed, Coursier's `--system-jvm` option will be used"
                " instead, but note that this can lead to inconsistent behavior since the JVM version"
                " will be whatever happens to be found first on the system's PATH."
            ),
        )

    @property
    def args(self) -> list[str]:
        return cast("list[str]", self.options.args)
