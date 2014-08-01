# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class RankedValue(object):
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
  CONFIG = 2  # The value from the config file.
  ENVIRONMENT = 3  # The value from the appropriately-named environment variable.
  FLAG = 4  # The value from the appropriately-named command-line flag.

  _RANK_NAMES = {
    NONE: 'NONE',
    HARDCODED: 'HARDCODED',
    CONFIG: 'CONFIG',
    ENVIRONMENT: 'ENVIRONMENT',
    FLAG: 'FLAG'
  }

  @classmethod
  def choose(cls, flag_val, env_val, config_val, hardcoded_val):
    """Return the highest-ranked non-None value, wrapped in a RankedValue instance."""
    if flag_val is not None:
      return RankedValue(cls.FLAG, flag_val)
    elif env_val is not None:
      return RankedValue(cls.ENVIRONMENT, env_val)
    elif config_val is not None:
      return RankedValue(cls.CONFIG, config_val)
    elif hardcoded_val is not None:
      return RankedValue(cls.HARDCODED, hardcoded_val)
    else:
      return RankedValue(cls.NONE, None)

  def __init__(self, rank, value):
    self._rank = rank
    self._value = value

  @property
  def rank(self):
    return self._rank

  @property
  def value(self):
    return self._value

  def __eq__(self):
    return self._rank == self._rank and self._value == self._value

  def __repr__(self):
    return '(%s, %s)' % (self._RANK_NAMES.get(self._rank, 'UNKNOWN'), self._value)
