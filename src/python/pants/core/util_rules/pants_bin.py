# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import cast

from pants.engine.rules import rule
from pants.option.global_options import GlobalOptions


@dataclass(frozen=True)
class PantsBin:
    name: str

    def render_command(
        self, *args: str, format_vertical: bool = False, continuation_indent: str = "\t"
    ) -> str:
        """Renders the given args as a valid Pants command line for the current Pants executable.

        The `continuation_indent` will only be used for folded continuation line if
        `format_vertical` is chosen.
        """
        cmd = [self.name, *args]
        joined_by = f" \\\n{continuation_indent}" if format_vertical else " "
        return joined_by.join(cmd)


@rule
def pants_bin(global_options: GlobalOptions) -> PantsBin:
    pants_bin_name = cast(str, global_options.options.pants_bin_name)
    return PantsBin(name=pants_bin_name)


def rules():
    return [pants_bin]
