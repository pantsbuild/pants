# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections
from typing import Callable, DefaultDict, Iterable, MutableMapping, TypeVar


_K = TypeVar("_K")
_V = TypeVar("_V")


def factory_dict(value_factory: Callable[[_K], _V], *args, **kwargs) -> DefaultDict:
  """A dict whose values are computed by `value_factory` when a `__getitem__` key is missing.

  Note that values retrieved by any other method will not be lazily computed; eg: via `get`.

  :param value_factory:
  :param *args: Any positional args to pass through to `dict`.
  :param **kwrags: Any kwargs to pass through to `dict`.
  """

  class FactoryDict(collections.defaultdict):
    @staticmethod
    def __never_called():
      raise AssertionError(
        "The default factory should never be called since we override " "__missing__."
      )

    def __init__(self):
      super().__init__(self.__never_called, *args, **kwargs)

    def __missing__(self, key):
      value = value_factory(key)
      self[key] = value
      return value

  return FactoryDict()


def recursively_update(d: MutableMapping, d2: MutableMapping) -> None:
  """dict.update but which merges child dicts (dict2 takes precedence where there's conflict)."""
  for k, v in d2.items():
    if k in d:
      if isinstance(v, dict):
        recursively_update(d[k], v)
        continue
    d[k] = v


_T = TypeVar("_T")


def assert_single_element(iterable: Iterable[_T]) -> _T:
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

  raise ValueError(f"iterable {iterable!r} has more than one element.")
