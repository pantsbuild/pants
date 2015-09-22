# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.option.errors import ParseError
from pants.util.eval import parse_expression


def dict_option(s):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a dict.
  """
  return _convert(s, (dict,))


def list_option(s):
  """An option of type 'list'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a
  list or tuple.
  """
  return _convert(s, (list, tuple))


def target_list_option(s):
  """Same type as 'list_option', but indicates list contents are target specs."""
  return _convert(s, (list, tuple))


def file_option(s):
  """Same type as 'str', but indicates string represents a filepath."""
  if not os.path.isfile(s):
    raise ParseError('Options file "{filepath}" does not exist.'.format(filepath=s))
  return s


def _convert(val, acceptable_types):
  """Ensure that val is one of the acceptable types, converting it if needed.

  :param string val: The value we're parsing.
  :param acceptable_types: A tuple of expected types for val.
  :returns: The parsed value.
  :raises :class:`pants.options.errors.ParseError`: if there was a problem parsing the val as an
                                                    acceptable type.
  """
  return parse_expression(val, acceptable_types, raise_type=ParseError)
