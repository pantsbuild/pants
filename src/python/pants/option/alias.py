# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from typing import Generator

from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


class CliOptions(Subsystem):
    options_scope = "cli"

    @staticmethod
    def register_options(register):
        register(
            "--alias",
            type=dict,
            default={},
            help=(
                "Register command line aliases.\nExample:\n\n"
                "    [cli.alias]\n"
                '    green = "fmt lint check"\n'
                '    all-changed = "--changed-since=HEAD --changed-dependees=transitive"\n'
                "\n"
                "This would allow you to run `./pants green all-changed`, which is shorthand for "
                "`./pants fmt lint check --changed-since=HEAD --changed-dependees=transitive`.\n\n"
                "Notice: this option must be placed in a config file (e.g. `pants.toml`) to have "
                "any effect."
            ),
        )


@dataclass(frozen=True)
class CliAlias:
    definitions: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)

    @classmethod
    def from_dict(cls, definitions: dict[str, str]) -> CliAlias:
        return cls(
            FrozenDict({key: tuple(shlex.split(value)) for key, value in definitions.items()})
        )

    def expand_args(self, args: tuple[str, ...]) -> tuple[str, ...]:
        if not self.definitions:
            return args
        return tuple(self._do_expand_args(args))

    def _do_expand_args(self, args: tuple[str, ...]) -> Generator[str, None, None]:
        args_iter = iter(args)
        for arg in args_iter:
            if arg == "--":
                # Do not expand pass through arguments.
                yield arg
                yield from args_iter
                return

            expanded = self.maybe_expand(arg)
            if expanded:
                logger.debug(f"Expanded [cli.alias].{arg} => {' '.join(expanded)}")
                yield from expanded
            else:
                yield arg

    def maybe_expand(self, arg: str) -> tuple[str, ...] | None:
        return self.definitions.get(arg)
