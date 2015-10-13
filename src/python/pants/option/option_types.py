# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from six import string_types

from pants.option.errors import ParseError
from pants.option.option_type import OptionType, PrimitiveOptionType


class BooleanConversionError(ParseError):
  """Indicates a value other than 'True' or 'False' when attempting to parse a bool."""


class FileOption(OptionType):
  """The type for options representing files."""

  @classmethod
  def from_untyped(cls, s):
    if not os.path.isfile(s):
      raise ParseError('Options file "{filepath}" does not exist.'.format(filepath=s))
    return s

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    """Hashes the given option_val into the given hasher."""
    hasher.update(option_val)
    with open(option_val, 'rb') as f:
      hasher.update(f.read())


class DictOption(PrimitiveOptionType):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a dict.
  """

  @classmethod
  def from_untyped(cls, s):
    return cls._convert(s, (dict,))


class ListOption(PrimitiveOptionType):
  """An option of type 'list'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a
  list or tuple.
  """

  @classmethod
  def from_untyped(cls, s):
    return cls._convert(s, (list, tuple))


class BoolOption(PrimitiveOptionType):

  @classmethod
  def from_untyped(cls, s):
    if isinstance(s, string_types):
      if s.lower() == 'true':
        return True
      elif s.lower() == 'false':
        return False
      else:
        raise BooleanConversionError('Got "{0}". Expected "True" or "False".'.format(s))
    if s is True:
      return True
    elif s is False:
      return False
    else:
      raise BooleanConversionError('Got {0}. Expected True or False.'.format(s))


class StrOption(PrimitiveOptionType):

  @classmethod
  def from_untyped(cls, s):
    return s


class IntOption(PrimitiveOptionType):

  @classmethod
  def from_untyped(cls, s):
    return int(s)


class FloatOption(PrimitiveOptionType):

  @classmethod
  def from_untyped(cls, s):
    return float(s)
