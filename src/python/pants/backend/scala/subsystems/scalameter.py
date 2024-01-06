# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import BoolOption, IntOption, SkipOption


class Scalameter(JvmToolBase):
    options_scope = "scalameter"
    name = "Scalameter"
    help = "The ScalaMeter benchmark framework (https://scalameter.github.io)"

    default_version = "0.21"
    default_artifacts = ("com.storm-enroute:scalameter_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.subsystems",
        "scalameter.default.lockfile.txt",
    )

    min_warmups = IntOption(
        "--min-warmups",
        default=None,
        help="Minimum number of warm up cycles to run before the benchmark",
    )
    max_warmups = IntOption(
        "--max-warmups",
        default=None,
        help="Maximum number of warm up cycles to run before the benchmark",
    )
    runs = IntOption("--runs", default=None, help="Number of run cycles for the benchmark")
    colors = BoolOption("--colors", default=None, help="Use colours in standard output")
    skip = SkipOption("bench")
