# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address import Address
from pants.option.errors import ParseError
from pants.util.eval import parse_expression


def target_option(s):
  """An option of type 'Address', which is parsed from a target address spec string."""
  try:
    return Address.parse(s)
  except Exception as e:
    raise ParseError(
        'This option expects a single target address spec. Parse failed with: {}'.format(e))

def target_list_option(s):
  """An option of type 'list' of 'Address', which is parsed from target address spec strings."""
  addresses = []
  for entry in _convert(s, (list, tuple)):
    try:
      addresses.append(Address.parse(entry))
    except Exception as e:
      raise ParseError(
          'This option expects a list of target address specs. Parse failed with: {}'.format(e))
  return addresses

def _convert(val, acceptable_types):
  """Ensure that val is one of the acceptable types, converting it if needed.

  :param string val: The value we're parsing.
  :param acceptable_types: A tuple of expected types for val.
  :returns: The parsed value.
  :raises :class:`pants.options.errors.ParseError`: if there was a problem parsing the val as an
                                                    acceptable type.
  """
  return parse_expression(val, acceptable_types, raise_type=ParseError)
