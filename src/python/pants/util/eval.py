# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

import six


def parse_expression(val, acceptable_types, name=None, raise_type=ValueError):
  """Attempts to parse the given `val` as a python expression of the specified `acceptable_types`.

  :param string val: A string containing a python expression.
  :param acceptable_types: The acceptable types of the parsed object.
  :type acceptable_types: type|tuple of types.  The tuple may be nested; ie anything `isinstance`
                          accepts.
  :param string name: An optional logical name for the value being parsed; ie if the literal val
                      represents a person's age, 'age'.
  :param type raise_type: The type of exception to raise for all failures; ValueError by default.
  :raises: If `val` is not a valid python literal expression or it is but evaluates to an object
           that is not a an instance of one of the `acceptable_types`.
  """
  def format_type(typ):
    return typ.__name__

  if not isinstance(val, six.string_types):
    raise raise_type('The raw `val` is not a string.  Given {} of type {}.'
                     .format(val, format_type(type(val))))

  def get_name():
    return repr(name) if name else 'value'

  def format_raw_value():
    lines = val.splitlines()
    for line_number in six.moves.range(0, len(lines)):
      lines[line_number] = "{line_number:{width}}: {line}".format(
        line_number=line_number + 1,
        line=lines[line_number],
        width=len(str(len(lines))))
    return '\n'.join(lines)

  try:
    parsed_value = eval(val)
  except (ValueError, SyntaxError) as e:
    raise raise_type(dedent("""\
      The {name} cannot be evaluated as a literal expression: {error}
      Given raw value:
      {value}
      """.format(name=get_name(),
                 error=e,
                 value=format_raw_value())))
  if not isinstance(parsed_value, acceptable_types):
    def iter_types(types):
      if isinstance(types, type):
        yield types
      elif isinstance(types, tuple):
        for item in types:
          for typ in iter_types(item):
            yield typ
      else:
        raise ValueError('The given acceptable_types is not a valid type (tuple): {}'
                         .format(acceptable_types))

    raise raise_type(dedent("""\
      The {name} is not of the expected type(s): {types}:
      Given the following raw value that evaluated to type {type}:
      {value}
      """.format(name=get_name(),
                 types=', '.join(format_type(t) for t in iter_types(acceptable_types)),
                 type=format_type(type(parsed_value)),
                 value=format_raw_value())))
  return parsed_value
