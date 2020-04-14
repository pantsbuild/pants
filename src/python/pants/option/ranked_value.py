# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
from typing import Any, Dict, Iterator, List, Union


@total_ordering
class Rank(Enum):
    # The ranked value sources. Higher ranks override lower ones.
    NONE = (0, "NONE")  # The value None.
    HARDCODED = (1, "HARDCODED")  # The default provided at option registration.
    CONFIG_DEFAULT = (2, "CONFIG_DEFAULT")  # The value from the DEFAULT section of the config file.
    CONFIG = (3, "CONFIG")  # The value from the relevant section of the config file.
    ENVIRONMENT = (4, "ENVIRONMENT")  # The value from the appropriately-named environment variable.
    FLAG = (5, "FLAG")  # The value from the appropriately-named command-line flag.

    _rank: int

    def __new__(cls, rank: int, display: str) -> "Rank":
        member: "Rank" = object.__new__(cls)
        member._value_ = display
        member._rank = rank
        return member

    def __lt__(self, other: Any) -> Union["NotImplemented", bool]:
        if type(other) != Rank:
            return NotImplemented
        return self._rank < other._rank


Value = Union[str, int, float, None, Dict, Enum, List]


@dataclass(frozen=True)
class RankedValue:
    """An option value, together with a rank inferred from its source.

     Allows us to control which source wins: e.g., a command-line flag overrides an environment
     variable which overrides a config, etc. For example:

     Consider this config:

     [compile.java]
     foo: 11

     And this environment variable:

     PANTS_COMPILE_FOO: 22

    If the command-line is

     ./pants compile target

     we expect the value of foo in the compile.java scope to be 22, because it was explicitly
     set by the user in the enclosing compile scope. I.e., the outer scope's environment value
     overrides the inner scope's config value.

     However if the command-line is

     ./pants compile.java --foo=33 target

     we now expect the value of foo in the compile.java to be 33. I.e., the inner scope's flag
     overrides the outer scope's environment value.

     To tell these cases apart we need to know the "ranking" of the value.
    """

    @classmethod
    def prioritized_iter(
        cls,
        flag_val: Value,
        env_val: Value,
        config_val: Value,
        config_default_val: Value,
        hardcoded_val: Value,
        default: Value,
    ) -> Iterator["RankedValue"]:
        """Yield the non-None values from highest-ranked to lowest, wrapped in RankedValue
        instances."""
        if flag_val is not None:
            yield RankedValue(Rank.FLAG, flag_val)
        if env_val is not None:
            yield RankedValue(Rank.ENVIRONMENT, env_val)
        if config_val is not None:
            yield RankedValue(Rank.CONFIG, config_val)
        if config_default_val is not None:
            yield RankedValue(Rank.CONFIG_DEFAULT, config_default_val)
        if hardcoded_val is not None:
            yield RankedValue(Rank.HARDCODED, hardcoded_val)
        yield RankedValue(Rank.NONE, default)

    rank: Rank
    value: Value
