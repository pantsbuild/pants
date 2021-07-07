# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class JavacSubsystem(Subsystem):
    options_scope = "javac"
    help = "The javac Java source compiler."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--jdk",
            default="adopt:1.11",
            advanced=True,
            help="The JDK to use for invoking javac."
            " This string will be passed directly to Coursier's `--jvm` parameter."
            " Run `cs java --available` to see a list of available JVM versions on your platform.",
        )
