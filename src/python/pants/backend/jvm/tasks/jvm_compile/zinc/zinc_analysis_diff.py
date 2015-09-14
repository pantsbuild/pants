# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import OrderedDict

import six


# TODO(benjy): Move to a util package?
class DictDiff(object):
  """Represents a diff between two dicts.

  Useful in tests.
  """

  def __init__(self, left_dict, right_dict, keys_only=False):
    left_keys = set(left_dict.keys())
    right_keys = set(right_dict.keys())
    self._left_missing_keys = right_keys - left_keys
    self._right_missing_keys = left_keys - right_keys
    self._diff_keys = {}  # Map of key -> (left value, right value)
    if not keys_only:
      shared_keys = left_keys & right_keys
      for key in shared_keys:
        left_value = left_dict[key]
        right_value = right_dict[key]
        if left_value != right_value:
          self._diff_keys[key] = (left_value, right_value)

  def is_different(self):
    return self._left_missing_keys or self._right_missing_keys or self._diff_keys

  def __unicode__(self):
    parts = []
    if self._left_missing_keys:
      parts.append('Keys missing from left but available in right: {}'
                   .format(', '.join(self._left_missing_keys)))
    if self._right_missing_keys:
      parts.append('Keys available in left but missing from right: {}'
                   .format(', '.join(self._right_missing_keys)))
    for k, vs in self._diff_keys.items():
      parts.append('Different values for key {}: left has {}, right has {}'.format(k, vs[0], vs[1]))
    return '\n'.join(parts)

  def __str__(self):
    if six.PY3:
      return self.__unicode__()
    else:
      return self.__unicode__().encode('utf-8')


class ZincAnalysisElementDiff(object):
  def __init__(self, left_elem, right_elem, keys_only_headers=None):
    left_type = type(left_elem)
    right_type = type(right_elem)
    if left_type != right_type:
      raise Exception('Cannot compare elements of types {} and {}'.format(left_type, right_type))
    self._arg_diffs = OrderedDict()
    for header, left_dict, right_dict in zip(left_elem.headers, left_elem.args, right_elem.args):
      keys_only = header in (keys_only_headers or [])
      self._arg_diffs[header] = DictDiff(left_dict, right_dict, keys_only=keys_only)

  def is_different(self):
    return any([x.is_different() for x in self._arg_diffs.values()])

  def __unicode__(self):
    parts = []
    for header, arg_diff in self._arg_diffs.items():
      if arg_diff.is_different():
        parts.append('Section "{}" differs:\n'.format(header))
        parts.append(six.text_type(arg_diff))
        parts.append('\n\n')
    return ''.join(parts)  # '' is a unicode, so the entire result will be.

  def __str__(self):
    if six.PY3:
      return self.__unicode__()
    else:
      return self.__unicode__().encode('utf-8')
