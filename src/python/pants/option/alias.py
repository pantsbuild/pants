# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from itertools import chain
from typing import Generator

from pants.base.deprecated import warn_or_error
from pants.option.errors import OptionsError
from pants.option.option_types import BoolOption, DictOption
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
                all-changed = "--changed-since=HEAD --changed-dependees=transitive"


            This would allow you to run `{bin_name()} green all-changed`, which is shorthand for
            `{bin_name()} fmt lint check --changed-since=HEAD --changed-dependees=transitive`.

            Notice: this option must be placed in a config file (e.g. `pants.toml` or `pantsrc`)
            to have any effect.
            """
        ),
    )
    _build_files_expand_to_targets = BoolOption(
        default=True,
        help=softwrap(
            f"""
            If true, then BUILD files used in CLI arguments will expand to all the
            targets they define. For example, `{bin_name()} fmt project/BUILD` will format all
            the targets defined in the BUILD file, not only the file `project/BUILD`.

            (We believe the more intuitive behavior is to set this option to `false`, which
            will become the default in Pants 2.15.)
            """
        ),
        advanced=True,
    )

    @property
    def build_files_expand_to_targets(self) -> bool:
        if self.options.is_default("build_files_expand_to_targets"):
            warn_or_error(
                "2.15.0.dev0",
                "`[cli].build_files_expand_to_targets` defaulting to true",
                softwrap(
                    f"""
                    Currently, by default, BUILD files used in CLI arguments will expand to all the
                    targets they define. For example, `{bin_name()} fmt project/BUILD` will format all
                    the targets defined in the BUILD file, not only the file `project/BUILD`. In
                    Pants 2.15, the default will change to no longer expand.

                    To silence this warning, set the option
                    `build_files_expand_to_targets` in the `[cli]` section of
                    `pants.toml` to either `true` or `false`. Generally, we recommend setting to
                    `false` for more intuitive behavior.
                    """
                ),
            )
        return self._build_files_expand_to_targets


@dataclass(frozen=True)
class CliAlias:
    definitions: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)

    def __post_init__(self):
        valid_alias_re = re.compile(r"\w(\w|-)*\w$", re.IGNORECASE)
        for alias in self.definitions.keys():
            if not re.match(valid_alias_re, alias):
                raise CliAliasInvalidError(
                    f"Invalid alias in `[cli].alias` option: {alias!r}. May only contain alpha "
                    "numerical letters and the separators `-` and `_`, and may not begin/end "
                    "with a `-`."
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
                            "CLI alias cycle detected in `[cli].alias` option: "
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

    def check_name_conflicts(self, known_scopes: dict[str, ScopeInfo]) -> None:
        for alias in self.definitions.keys():
            scope = known_scopes.get(alias)
            if scope:
                raise CliAliasInvalidError(
                    f"Invalid alias in `[cli].alias` option: {alias!r}. This is already a "
                    "registered " + ("goal." if scope.is_goal else "subsystem.")
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
