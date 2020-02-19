# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing

from pants.option.custom_types import shell_str
from pants.subsystem.subsystem import Subsystem


class ScroogeLinter(Subsystem):

    options_scope = "scrooge-linter"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            fingerprint=True,
            help="Arguments to pass directly to the Scrooge Thrift linter, e.g. "
            '`--scrooge-linter-args="--disable-rule Namespaces"`.',
        )
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use the Scrooge Thrift linter when running `./pants lint`.",
        )
        register(
            "--strict",
            type=bool,
            fingerprint=True,
            help="Fail the goal if thrift linter errors are found. Overrides the `strict-default` option.",
        )
        register(
            "--strict-default",
            default=False,
            advanced=True,
            type=bool,
            fingerprint=True,
            help="Sets the default strictness for targets. The `strict` option overrides this value if "
            "it is set.",
        )
        register(
            "--worker-count",
            default=multiprocessing.cpu_count(),
            advanced=True,
            type=int,
            help="Maximum number of workers to use for linter parallelization.",
        )
