# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import json

from pants.option.errors import ParseError


def _parse_error(s, msg):
  """Return a ParseError with a usefully formatted message, for the caller to throw.

  :param s: The option value we're parsing.
  :param msg: An extra message to add to the ParseError.
  """
  return ParseError('Error while parsing option value {0}: {1}'.format(s, msg))


def dict_type(s):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be a JSON object.
  """
  if isinstance(s, dict):
    return s
  try:
    ret = json.loads(s)
  except ValueError as e:
    raise _parse_error(s, e.message)
  if not isinstance(ret, dict):
    raise _parse_error(s, 'Value is not dict')
  return ret


def list_type(s):
  """An option of type 'list'.

  The value (on the command-line, in an env var or in the config file) must be a JSON list.
  """
  if isinstance(s, (list, tuple)):
    return s
  try:
    ret = json.loads(s)
  except ValueError as e:
    raise _parse_error(s, e.message)
  if not isinstance(ret, list):
    raise _parse_error(s, 'Value is not list')
  return ret
