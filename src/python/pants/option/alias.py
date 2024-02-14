# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from itertools import chain
from typing import Generator

from pants.option.errors import OptionsError
from pants.option.option_types import DictOption
from pants.option.scope import ScopeInfo
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class CliAliasError(OptionsError):
    pass


class CliAliasCycleError(CliAliasError):
    pass


class CliAliasInvalidError(CliAliasError):
    pass


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


@dataclass(frozen=True)
class CliAlias:
    definitions: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)

    def __post_init__(self):
        valid_alias_re = re.compile(r"(--)?\w(\w|-)*\w$", re.IGNORECASE)
        for alias in self.definitions.keys():
            if not re.match(valid_alias_re, alias):
                raise CliAliasInvalidError(
                    softwrap(
                        f"""
                        Invalid alias in `[cli].alias` option: {alias!r}. May only contain alpha
                        numerical letters and the separators `-` and `_`. Flags can be defined using
                        `--`. A single dash is not allowed.
                        """
                    )
                )

    @classmethod
    def from_dict(cls, aliases: dict[str, str]) -> CliAlias:
        definitions = {key: tuple(shlex.split(value)) for key, value in aliases.items()}

        def expand(
            definition: tuple[str, ...], *trail: str
        ) -> Generator[tuple[str, ...], None, None]:
            for arg in definition:
                if arg not in definitions:
                    yield (arg,)
                else:
                    if arg in trail:
                        raise CliAliasCycleError(
                            "CLI alias cycle detected in `[cli].alias` option:\n"
                            + " -> ".join([arg, *trail])
                        )
                    yield from expand(definitions[arg], arg, *trail)

        return cls(
            FrozenDict(
                {
                    alias: tuple(chain.from_iterable(expand(definition)))
                    for alias, definition in definitions.items()
                }
            )
        )

    def check_name_conflicts(
        self, known_scopes: dict[str, ScopeInfo], known_flags: dict[str, frozenset[str]]
    ) -> None:
        for alias in self.definitions.keys():
            scope = known_scopes.get(alias)

            if scope:
                raise CliAliasInvalidError(
                    softwrap(
                        f"""
                        Invalid alias in `[cli].alias` option: {alias!r}. This is already a
                        registered {"goal" if scope.is_goal else "subsystem"}.
                        """
                    )
                )

        for scope_name, args in known_flags.items():
            for alias in self.definitions.keys():
                if alias in args:
                    scope_name = scope_name or "global"
                    raise CliAliasInvalidError(
                        softwrap(
                            f"""
                            Invalid flag-like alias in `[cli].alias` option: {alias!r}. This is
                            already a registered flag in the {scope_name!r} scope.
                            """
                        )
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
