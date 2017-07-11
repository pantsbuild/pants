# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

import six

from pants.option.errors import ParseError
from pants.util.eval import parse_expression
from pants.util.memo import memoized_method
from pants.util.strutil import ensure_text


class UnsetBool(object):
  """A type that can be used as the default value for a bool typed option to indicate un-set.

  In other words, `bool`-typed options with a `default=UnsetBool` that are not explicitly set will
  have the value `None`, enabling a tri-state.

  :API: public
  """

  def __init__(self):
    raise NotImplementedError('UnsetBool cannot be instantiated. It should only be used as a '
                              'sentinel type.')


def dict_option(s):
  """An option of type 'dict'.

  The value (on the command-line, in an env var or in the config file) must be eval'able to a dict.

  :API: public
  """
  return DictValueComponent.create(s)


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


def dir_option(s):
  """Same type as 'str', but indicates string represents a directory path.

  :API: public
  """
  return s


def file_option(s):
  """Same type as 'str', but indicates string represents a filepath.

  :API: public
  """
  return s


def dict_with_files_option(s):
  """Same as 'dict', but fingerprints the file contents of any values which are file paths.

  For any value which matches the path of a file on disk, the file path is not fingerprinted -- only
  its contents.

  :API: public
  """
  return dict_option(s)


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

  A component consists of values to append and values to filter while constructing the final list.

  Each component may either replace or modify the preceding component.  So that, e.g., a config
  file can append to and/or filter the default value list, instead of having to repeat most
  of the contents of the default value list.
  """
  REPLACE = 'REPLACE'
  MODIFY = 'MODIFY'

  # We use a regex to parse the comma-separated lists of modifier expressions (each of which is
  # a list or tuple literal preceded by a + or a -).  Note that these expressions are technically
  # a context-free grammar, but in practice using this regex as a heuristic will work fine. The
  # values that could defeat it are extremely unlikely to be encountered in practice.
  # If we do ever encounter them, we'll have to replace this with a real parser.
  @classmethod
  @memoized_method
  def _get_modifier_expr_re(cls):
    # Note that the regex consists of a positive lookbehind assertion for a ] or a ),
    # followed by a comma (possibly surrounded by whitespace), followed by a
    # positive lookahead assertion for [ or (.  The lookahead/lookbehind assertions mean that
    # the bracket/paren characters don't get consumed in the split.
    return re.compile(r'(?<=\]|\))\s*,\s*(?=[+-](?:\[|\())')

  @classmethod
  def _split_modifier_expr(cls, s):
    # This check ensures that the first expression (before the first split point) is a modification.
    if s.startswith('+') or s.startswith('-'):
      return cls._get_modifier_expr_re().split(s)
    else:
      return [s]

  @classmethod
  def merge(cls, components):
    """Merges components into a single component, applying their actions appropriately.

    This operation is associative:  M(M(a, b), c) == M(a, M(b, c)) == M(a, b, c).

    :param list components: an iterable of instances of ListValueComponent.
    :return: An instance representing the result of merging the components.
    :rtype: `ListValueComponent`
    """
    # Note that action of the merged component is MODIFY until the first REPLACE is encountered.
    # This guarantees associativity.
    action = cls.MODIFY
    appends = []
    filters = []
    for component in components:
      if component._action is cls.REPLACE:
        appends = component._appends
        filters = component._filters
        action = cls.REPLACE
      elif component._action is cls.MODIFY:
        appends.extend(component._appends)
        filters.extend(component._filters)
      else:
        raise ParseError('Unknown action for list value: {}'.format(component.action))
    return cls(action, appends, filters)

  def __init__(self, action, appends, filters):
    self._action = action
    self._appends = appends
    self._filters = filters

  @property
  def val(self):
    ret = list(self._appends)
    for x in self._filters:
      # Note: can't do ret.remove(x) because that only removes the first instance of x.
      ret = [y for y in ret if y != x]
    return ret

  @classmethod
  def create(cls, value):
    """Interpret value as either a list or something to extend another list with.

    Note that we accept tuple literals, but the internal value is always a list.

    :param value: The value to convert.  Can be an instance of ListValueComponent, a list, a tuple,
                  a string representation of a list or tuple (possibly prefixed by + or -
                  indicating modification instead of replacement), or any allowed member_type.
                  May also be a comma-separated sequence of modifications.
    :rtype: `ListValueComponent`
    """
    if isinstance(value, six.string_types):
      value = ensure_text(value)
      comma_separated_exprs = cls._split_modifier_expr(value)
      if len(comma_separated_exprs) > 1:
        return cls.merge([cls.create(x) for x in comma_separated_exprs])

    action = cls.MODIFY
    appends = []
    filters = []
    if isinstance(value, cls):  # Ensure idempotency.
      action = value._action
      appends = value._appends
      filters = value._filters
    elif isinstance(value, (list, tuple)):  # Ensure we can handle list-typed default values.
      action = cls.REPLACE
      appends = value
    elif value.startswith('[') or value.startswith('('):
      action = cls.REPLACE
      appends = _convert(value, (list, tuple))
    elif value.startswith('+[') or value.startswith('+('):
      appends = _convert(value[1:], (list, tuple))
    elif value.startswith('-[') or value.startswith('-('):
      filters = _convert(value[1:], (list, tuple))
    elif isinstance(value, six.string_types):
      appends = [value]
    else:
      appends = _convert('[{}]'.format(value), list)
    return cls(action, list(appends), list(filters))

  def __repr__(self):
    return b'{} +{} -{}'.format(self._action, self._appends, self._filters)


class DictValueComponent(object):
  """A component of the value of a dict-typed option.

  One or more instances of this class can be merged to form a dict value.

  Each component may either replace or extend the preceding component.  So that, e.g., a config
  file can extend the default value of a dict, instead of having to repeat it.
  """
  REPLACE = 'REPLACE'
  EXTEND = 'EXTEND'

  @classmethod
  def merge(cls, components):
    """Merges components into a single component, applying their actions appropriately.

    This operation is associative:  M(M(a, b), c) == M(a, M(b, c)) == M(a, b, c).

    :param list components: an iterable of instances of DictValueComponent.
    :return: An instance representing the result of merging the components.
    :rtype: `DictValueComponent`
    """
    # Note that action of the merged component is EXTEND until the first REPLACE is encountered.
    # This guarantees associativity.
    action = cls.EXTEND
    val = {}
    for component in components:
      if component.action is cls.REPLACE:
        val = component.val
        action = cls.REPLACE
      elif component.action is cls.EXTEND:
        val.update(component.val)
      else:
        raise ParseError('Unknown action for dict value: {}'.format(component.action))
    return cls(action, val)

  def __init__(self, action, val):
    self.action = action
    self.val = val

  @classmethod
  def create(cls, value):
    """Interpret value as either a dict or something to extend another dict with.

    :param value: The value to convert.  Can be an instance of DictValueComponent, a dict,
                  or a string representation (possibly prefixed by +) of a dict.
    :rtype: `DictValueComponent`
    """
    if isinstance(value, six.string_types):
      value = ensure_text(value)
    if isinstance(value, cls):  # Ensure idempotency.
      action = value.action
      val = value.val
    elif isinstance(value, dict):  # Ensure we can handle dict-typed default values.
      action = cls.REPLACE
      val = value
    elif value.startswith('{'):
      action = cls.REPLACE
      val = _convert(value, dict)
    elif value.startswith('+{'):
      action = cls.EXTEND
      val = _convert(value[1:], dict)
    else:
      raise ParseError('Invalid dict value: {}'.format(value))
    return cls(action, dict(val))

  def __repr__(self):
    return b'{} {}'.format(self.action, self.val)
