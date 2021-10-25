# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = "Options for general JVM functionality."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--resolves",
            type=dict,
            help=("A dictionary, mapping resolve names to the path of their lockfile. "),
        )

        register(
            "--default-resolve",
            type=str,
            help=(
                "The name of the resolve to use by default, if a specific one is not specified "
                "using `--coursier-resolve-name`. This name must be one of the keys specified in "
                "`--jvm-resolves`."
            ),
        )
