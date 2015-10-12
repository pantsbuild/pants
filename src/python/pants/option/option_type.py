# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.option.errors import ParseError
from pants.util.eval import parse_expression
from pants.util.meta import AbstractClass


class OptionType(AbstractClass):
  """The type of an option value.
  
  Provides methods to convert user input to the type, and to fingerprint the type.
  """

  @classmethod
  def _stable_json_dumps(cls, obj):
    return json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True)

  @classmethod
  def _convert(cls, val, acceptable_types):
    """Ensure that val is one of the acceptable types, converting it if needed.

    :param string val: The value we're parsing.
    :param acceptable_types: A tuple of expected types for val.
    :returns: The parsed value.
    :raises :class:`pants.options.errors.ParseError`: if there was a problem parsing the val as an
                                                      acceptable type.
    """
    return parse_expression(val, acceptable_types, raise_type=ParseError)

  @classmethod
  @abstractmethod
  def from_untyped(cls, s):
    """Converts the given python string to this type, and returns the typed value."""
    pass

  @classmethod
  @abstractmethod
  def fingerprint(cls, context, hasher, option_val):
    """Hashes the given option_val into the given hasher."""
    pass


class PrimitiveOptionType(OptionType):
  """An abstract base class for options with primitive values."""

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    """Hashes the given option_val into the given hasher."""
    hasher.update(cls._stable_json_dumps(option_val))
