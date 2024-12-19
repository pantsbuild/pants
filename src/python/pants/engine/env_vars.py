# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

name_value_re = re.compile(r"([A-Za-z_]\w*)=(.*)")
shorthand_re = re.compile(r"([A-Za-z_]\w*)")


class CompleteEnvironmentVars(FrozenDict):
    """CompleteEnvironmentVars contains all environment variables from the current Pants process.

    NB: Consumers should almost always prefer to consume the `EnvironmentVars` type, which is
    filtered to a relevant subset of the environment.
    """

    def get_subset(
        self, requested: Sequence[str], *, allowed: Optional[Sequence[str]] = None
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
        env_var_subset: Dict[str, str] = {}

        def check_and_set(name: str, value: Optional[str]):
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
                for name, value in self.get_or_match(env_var).items():
                    check_and_set(name, value)
            else:
                raise ValueError(
                    f"An invalid variable was requested via the --test-extra-env-var "
                    f"mechanism: {env_var}"
                )

        return FrozenDict(env_var_subset)

    def get_or_match(self, name_or_pattern: str) -> dict[str, str]:
        """Get the value of an envvar if it has an exact match, otherwise all fnmatches."""
        if name_or_pattern in self:
            return {name_or_pattern: self.get(name_or_pattern)}
        return {k: v for k, v in self.items() if fnmatch.fnmatch(k, name_or_pattern)}


@dataclass(frozen=True)
class EnvironmentVarsRequest:
    """Requests a subset of the variables set in the environment.

    Requesting only the relevant subset of the environment reduces invalidation caused by unrelated
    changes.
    """

    requested: FrozenOrderedSet[str]
    allowed: Optional[FrozenOrderedSet[str]]

    def __init__(self, requested: Sequence[str], allowed: Optional[Sequence[str]] = None):
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
