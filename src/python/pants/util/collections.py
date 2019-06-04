# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections
from builtins import next


def combined_dict(*dicts):
  """Combine one or more dicts into a new, unified dict (dicts to the right take precedence)."""
  return {k: v for d in dicts for k, v in d.items()}


def factory_dict(value_factory, *args, **kwargs):
  """A dict whose values are computed by `value_factory` when a `__getitem__` key is missing.

  Note that values retrieved by any other method will not be lazily computed; eg: via `get`.

  :param value_factory:
  :type value_factory: A function from dict key to value.
  :param *args: Any positional args to pass through to `dict`.
  :param **kwrags: Any kwargs to pass through to `dict`.
  :rtype: dict
  """
  class FactoryDict(collections.defaultdict):
    @staticmethod
    def __never_called():
      raise AssertionError('The default factory should never be called since we override '
                           '__missing__.')

    def __init__(self):
      super(FactoryDict, self).__init__(self.__never_called, *args, **kwargs)

    def __missing__(self, key):
      value = value_factory(key)
      self[key] = value
      return value

  return FactoryDict()


def recursively_update(d, d2):
  """dict.update but which merges child dicts (dict2 takes precedence where there's conflict)."""
  for k, v in d2.items():
    if k in d:
      if isinstance(v, dict):
        recursively_update(d[k], v)
        continue
    d[k] = v


def assert_single_element(iterable):
  """Get the single element of `iterable`, or raise an error.

  :raise: :class:`StopIteration` if there is no element.
  :raise: :class:`ValueError` if there is more than one element.
  """
  it = iter(iterable)
  first_item = next(it)

  try:
    next(it)
  except StopIteration:
    return first_item

  raise ValueError("iterable {!r} has more than one element.".format(iterable))
