# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Generator

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class OptionAlias:
    definitions: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)

    @classmethod
    def from_dict(cls, definitions: dict[str, str]) -> OptionAlias:
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
                yield arg
                yield from args_iter
                return

            expanded = self.maybe_expand(arg)
            if expanded:
                yield from expanded
            else:
                yield arg

    def maybe_expand(self, arg: str) -> tuple[str, ...] | None:
        return self.definitions.get(arg)
