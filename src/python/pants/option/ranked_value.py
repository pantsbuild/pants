# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Union, cast


Rank = int
Value = Union[str, int, float, None, Dict, Enum, List]


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

  # The ranked value sources. Higher ranks override lower ones.
  NONE = 0  # The value None.
  HARDCODED = 1  # The default provided at option registration.
  CONFIG_DEFAULT = 2  # The value from the DEFAULT section of the config file.
  CONFIG = 3  # The value from the relevant section of the config file.
  ENVIRONMENT = 4  # The value from the appropriately-named environment variable.
  FLAG = 5  # The value from the appropriately-named command-line flag.

  _RANK_NAMES = {
    NONE: "NONE",
    HARDCODED: "HARDCODED",
    CONFIG_DEFAULT: "CONFIG_DEFAULT",
    CONFIG: "CONFIG",
    ENVIRONMENT: "ENVIRONMENT",
    FLAG: "FLAG",
  }

  @classmethod
  def get_rank_name(cls, rank: Rank) -> str:
    """Returns the string name for the given rank integer.

    :param rank: the integer rank constant (E.g., RankedValue.HARDCODED).
    :returns: the string name of the rank.
    """
    return cls._RANK_NAMES.get(rank, "UNKNOWN")

  @classmethod
  def get_rank_value(cls, name: str) -> Optional[Rank]:
    """Returns the integer constant value for the given rank name.

    :param name: the string rank name (E.g., 'HARDCODED').
    :returns: the integer constant value of the rank.
    """
    if name in cls._RANK_NAMES.values():
      return cast(Optional[Rank], getattr(cls, name, None))
    return None

  @classmethod
  def get_names(cls) -> List[str]:
    """Returns the list of rank names.

    :returns: the rank names as a list (I.e., ['NONE', 'HARDCODED', 'CONFIG', ...])
    """
    return sorted(cls._RANK_NAMES.values(), key=cls.get_rank_value)

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
    """Yield the non-None values from highest-ranked to lowest, wrapped in RankedValue instances."""
    if flag_val is not None:
      yield RankedValue(cls.FLAG, flag_val)
    if env_val is not None:
      yield RankedValue(cls.ENVIRONMENT, env_val)
    if config_val is not None:
      yield RankedValue(cls.CONFIG, config_val)
    if config_default_val is not None:
      yield RankedValue(cls.CONFIG_DEFAULT, config_default_val)
    if hardcoded_val is not None:
      yield RankedValue(cls.HARDCODED, hardcoded_val)
    yield RankedValue(cls.NONE, default)

  def __init__(self, rank: Rank, value: Value) -> None:
    self._rank = rank
    self._value = value

  @property
  def rank(self) -> Rank:
    return self._rank

  @property
  def value(self) -> Value:
    return self._value

  def __eq__(self, other: Any) -> bool:
    if not isinstance(other, RankedValue):
      return NotImplemented
    return self._rank == other._rank and self._value == other._value

  def __repr__(self) -> str:
    return f"({self.get_rank_name(self._rank)}, {self._value})"
