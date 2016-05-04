# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.option.errors import ParseError
from pants.util.eval import parse_expression
from pants.util.strutil import ensure_text


def dict_option(s):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a dict.

  :API: public
  """
  return _convert(s, (dict,))


def list_option(s):
  """An option of type 'list'.

  The value (on the command-line, in an env var or in the config file) must be one of:

  1. A string eval'able to a list or tuple, which will replace any previous values.
  2. A plus sign followed by a string eval'able to a list or a tuple, whose values will be
     appended to any previous values (e.g., those from lower-ranked sources).
  3. A scalar, that will be appended to any previous values.


  :API: public
  """
  return ListValueComponent.create(s)


def target_option(s):
  """Same type as 'str', but indicates a single target spec.

  :API: public

  TODO(stuhood): Eagerly convert these to Addresses: see https://rbcommons.com/s/twitter/r/2937/
  """
  return s


# TODO: Replace target_list_option with type=list, member_type=target_option.
# Then we'll get all the goodies from list_option (e.g., appending) free.
def target_list_option(s):
  """Same type as 'list_option', but indicates list contents are target specs.

  :API: public

  TODO(stuhood): Eagerly convert these to Addresses: see https://rbcommons.com/s/twitter/r/2937/
  """
  return _convert(s, (list, tuple))


def file_option(s):
  """Same type as 'str', but indicates string represents a filepath.

  :API: public
  """
  return s


def _convert(val, acceptable_types):
  """Ensure that val is one of the acceptable types, converting it if needed.

  :param val: The value we're parsing (either a string or one of the acceptable types).
  :param acceptable_types: A tuple of expected types for val.
  :returns: The parsed value.
  :raises :class:`pants.options.errors.ParseError`: if there was a problem parsing the val as an
                                                    acceptable type.
  """
  if isinstance(val, acceptable_types):
    return val
  return parse_expression(val, acceptable_types, raise_type=ParseError)


class ListValueComponent(object):
  """A component of the value of a list-typed option.

  One or more instances of this class can be merged to form a list value.

  Each component may either replace or extend the preceding component.  So that, e.g., a cmd-line
  flag can append to the value specified in the config file, instead of having to repeat it.
  """
  REPLACE = 'REPLACE'
  EXTEND = 'EXTEND'

  @classmethod
  def merge(cls, components):
    """Merges components into a single component, applying their actions appropriately.

    This operation is associative:  M(M(a, b), c) == M(a, M(b, c)) == M(a, b, c).

    :param list components: an iterable of instances of ListValueComponent.
    :return: An instance representing the result of merging the components.
    :rtype: `ListValueComponent`
    """
    # Note that action of the merged component is EXTEND until the first REPLACE is encountered.
    # This guarantees associativity.
    action = cls.EXTEND
    val = []
    for component in components:
      if component.action is cls.REPLACE:
        val = component.val
        action = cls.REPLACE
      elif component.action is cls.EXTEND:
        val.extend(component.val)
      else:
        raise ParseError('Unknown action for list value: {}'.format(component.action))
    return cls(action, val)

  def __init__(self, action, val):
    self.action = action
    self.val = val

  @classmethod
  def create(cls, value):
    """Interpret value as either a list or something to extend another list with.

    Note that we accept tuple literals, but the internal value is always a list.

    :param value: The value to convert.  Can be an instance of ListValueComponent, a list, a tuple,
           a string representation (possibly prefixed by +) of a list or tuple, or any allowed
           member_type.
    :rtype: `ListValueComponent`
    """
    if isinstance(value, six.string_types):
      value = ensure_text(value)
    if isinstance(value, cls):  # Ensure idempotency.
      action = value.action
      val = value.val
    elif isinstance(value, (list, tuple)):  # Ensure we can handle list-typed default values.
      action = cls.REPLACE
      val = value
    elif value.startswith('[') or value.startswith('('):
      action = cls.REPLACE
      val = _convert(value, (list, tuple))
    elif value.startswith('+[') or value.startswith('+('):
      action = cls.EXTEND
      val = _convert(value[1:], (list, tuple))
    elif isinstance(value, six.string_types):
      action = cls.EXTEND
      val = [value]
    else:
      action = cls.EXTEND
      val = _convert('[{}]'.format(value), list)
    return cls(action, list(val))

  def __repr__(self):
    return b'{} {}'.format(self.action, self.val)
