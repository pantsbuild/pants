# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections
from enum import Enum as StdLibEnum
from typing import (
  Callable,
  DefaultDict,
  Iterable,
  Mapping,
  MutableMapping,
  TypeVar,
  ValuesView,
  cast,
)


_K = TypeVar('_K')
_V = TypeVar('_V')


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
      raise AssertionError('The default factory should never be called since we override '
                           '__missing__.')

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


_T = TypeVar('_T')


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


_E = TypeVar('_E', bound='Enum')


class EnumMatchError(ValueError):
  """Issue when using match() on an enum."""


class InexhaustiveMatchError(EnumMatchError):
  """Not all values of the enum specified in the pattern match."""


class UnrecognizedMatchError(EnumMatchError):
  """A value is used that is not a part of the enum."""


class Enum(StdLibEnum):

  @classmethod
  def all_values(cls) -> ValuesView['Enum']:
    return cls.__members__.values()

  def match(self, enum_values_to_results: Mapping[_E, _V]) -> _V:
    unrecognized_values = [
      value for value in enum_values_to_results if value not in self.all_values()
    ]
    missing_values = [
      value for value in self.all_values() if value not in enum_values_to_results
    ]
    if unrecognized_values:
      raise UnrecognizedMatchError(
        f"Match includes values not defined in the enum. Unrecognized: {unrecognized_values}"
      )
    if missing_values:
      raise InexhaustiveMatchError(
        f"All enum values must be covered by the match. Missing: {missing_values}"
      )
    typed_self = cast(_E, self)
    return enum_values_to_results[typed_self]
