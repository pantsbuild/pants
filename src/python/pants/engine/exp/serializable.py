# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
from abc import abstractmethod

from pants.util.meta import AbstractClass


class Serializable(AbstractClass):
  """Marks a class that can be serialized into and reconstituted from python builtin values."""

  @staticmethod
  def is_serializable(obj):
    return isinstance(obj, Serializable) or (not inspect.isclass(obj) and hasattr(obj, '_asdict'))

  @abstractmethod
  def _asdict(self):
    """Return a dict mapping this class' properties.

    To meet the contract of a serializable the constructor must accept all the properties returned
    here as constructor parameters; ie the following must be true::

    >>> s = Serializable(...)
    >>> Serializable(**s._asdict()) == s

    Additionally the dict must also contain nothing except python primitive values, ie: dicts,
    lists, strings, numbers, bool values, etc.

    Any :class:`collections.namedtuple` satisfies the Serializable contract automatically via duck
    typing if it is composed of only primitive python values or Serializable values.
    """
