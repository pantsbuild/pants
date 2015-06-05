# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.config import Config
from pants.option.errors import ParseError


def _parse_error(s, msg):
  """Return a ParseError with a usefully formatted message, for the caller to throw.

  :param s: The option value we're parsing.
  :param msg: An extra message to add to the ParseError.
  """
  return ParseError('Error while parsing option value {0}: {1}'.format(s, msg))


def dict_type(s):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a dict.
  """
  return _convert(s, (dict,))


def list_type(s):
  """An option of type 'list'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a
  list or tuple.
  """
  return _convert(s, (list, tuple))


def _convert(val, acceptable_types):
  """Ensure that val is one of the acceptable types, converting it if needed.

  :param val: The value we're parsing.
  :param acceptable_types: A tuple of expected types for val.
  :returns: The parsed value
  """
  if isinstance(val, acceptable_types):
    return val
  try:
    parsed_value = eval(val, {}, {})
  except Exception as e:
    raise _parse_error(val, 'Value cannot be evaluated as an expression: '
                            '{msg}\n{value}\nAcceptable types: '
                            '{expected}'.format(
                                msg=e, value=Config.format_raw_value(val),
                                expected=format_type_tuple(acceptable_types)))
  if not isinstance(parsed_value, acceptable_types):
    raise _parse_error(val, 'Value is not of the acceptable types: '
                            '{msg}\n{''value}'.format(
                                msg=format_type_tuple(acceptable_types),
                                value=Config.format_raw_value(val)))
  return parsed_value


def format_type_tuple(type_tuple):
  """Return a list of type names from tuple of types."""
  return ", ".join([item.__name__ for item in type_tuple])
