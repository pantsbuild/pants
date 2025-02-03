# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

name_value_re = re.compile(r"([A-Za-z_]\w*)=(.*)")
shorthand_re = re.compile(r"([A-Za-z_]\w*)")

EXTRA_ENV_VARS_USAGE_HELP = """\
Entries are strings in the form `ENV_VAR=value` to use explicitly; or just
`ENV_VAR` to copy the value of a variable in Pants's own environment.
`fnmatch` globs like `ENV_VAR_PREFIXED_*` can be used to copy multiple environment variables.
"""


class CompleteEnvironmentVars(FrozenDict):
    """CompleteEnvironmentVars contains all environment variables from the current Pants process.

    NB: Consumers should almost always prefer to consume the `EnvironmentVars` type, which is
    filtered to a relevant subset of the environment.
    """

    def get_subset(
        self, requested: Sequence[str], *, allowed: Sequence[str] | None = None
    ) -> FrozenDict[str, str]:
        """Extract a subset of named env vars.

        Given a list of extra environment variable specifiers as strings, filter the contents of
        the Pants environment to only those variables.

        Each variable can be specified either as a name or as a name=value pair.
        In the former case, the value for that name is taken from this env. In the latter
        case the specified value overrides the value in this env.

        If `allowed` is specified, the requested variable names must be in that list, or an error
        will be raised.
        """
        allowed_set = None if allowed is None else set(allowed)
        env_var_subset: dict[str, str] = {}

        def check_and_set(name: str, value: str | None):
            if allowed_set is not None and name not in allowed_set:
                raise ValueError(
                    f"{name} is not in the list of variable names that are allowed to be set. "
                    f"Must be one of {','.join(sorted(allowed_set))}."
                )
            if value is not None:
                env_var_subset[name] = value

        for env_var in requested:
            name_value_match = name_value_re.match(env_var)
            if name_value_match:
                check_and_set(name_value_match[1], name_value_match[2])
            elif shorthand_re.match(env_var):
                for name, value in self.get_or_match(env_var):
                    check_and_set(name, value)
            else:
                raise ValueError(
                    f"An invalid variable was requested via the --test-extra-env-var "
                    f"mechanism: {env_var}"
                )

        return FrozenDict(env_var_subset)

    def get_or_match(self, name_or_pattern: str) -> Iterator[tuple[str, str]]:
        """Get the value of an envvar if it has an exact match, otherwise all fnmatches.

        Although fnmatch could also handle direct matches, it is significantly slower (roughly 2000
        times).
        """
        if value := self.get(name_or_pattern):
            yield name_or_pattern, value
            return  # do not check fnmatches if we have an exact match

        # fnmatch.filter looks tempting,
        # but we'd need to iterate once for the filtering the keys and again for getting the values
        for k, v in self.items():
            # we use fnmatchcase to avoid normalising the case with `os.path.normcase` on Windows systems
            if fnmatch.fnmatchcase(k, name_or_pattern):
                yield k, v


@dataclass(frozen=True)
class EnvironmentVarsRequest:
    """Requests a subset of the variables set in the environment.

    Requesting only the relevant subset of the environment reduces invalidation caused by unrelated
    changes.
    """

    requested: FrozenOrderedSet[str]
    allowed: FrozenOrderedSet[str] | None

    def __init__(self, requested: Sequence[str], allowed: Sequence[str] | None = None):
        object.__setattr__(self, "requested", FrozenOrderedSet(requested))
        object.__setattr__(self, "allowed", None if allowed is None else FrozenOrderedSet(allowed))


class EnvironmentVars(FrozenDict[str, str]):
    """A subset of the variables set in the environment.

    Accesses to `os.environ` cannot be accurately tracked, so @rules that need access to the
    environment should use APIs from this module instead.

    Wherever possible, the `EnvironmentVars` type should be consumed rather than the
    `CompleteEnvironmentVars`, as it represents a filtered/relevant subset of the environment, rather
    than the entire unfiltered environment.
    """


class PathEnvironmentVariable(FrozenOrderedSet):
    """The PATH environment variable entries, split on `os.pathsep`."""
