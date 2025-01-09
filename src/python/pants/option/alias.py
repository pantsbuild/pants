# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import DictOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


class CliOptions(Subsystem):
    options_scope = "cli"
    help = "Options for configuring CLI behavior, such as command line aliases."

    alias = DictOption[str](
        help=softwrap(
            f"""
            Register command line aliases.

            Example:

                [cli.alias]
                green = "fmt lint check"
                --all-changed = "--changed-since=HEAD --changed-dependents=transitive"


            This would allow you to run `{bin_name()} green --all-changed`, which is shorthand for
            `{bin_name()} fmt lint check --changed-since=HEAD --changed-dependents=transitive`.

            Notice: this option must be placed in a config file (e.g. `pants.toml` or `pantsrc`)
            to have any effect.
            """
        ),
    )
