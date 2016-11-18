# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def _satisfied_by(t, o):
  """Pickleable type check function."""
  return t.satisfied_by(o)


class State(AbstractClass):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))

  @staticmethod
  def from_components(components):
    """Given the components of a State, construct the State."""
    cls, remainder = components[0], components[1:]
    return cls._from_components(remainder)

  def to_components(self):
    """Return a flat tuple containing individual pickleable components of the State.

    TODO: Consider https://docs.python.org/2.7/library/pickle.html#pickling-and-unpickling-external-objects
    for this usecase?
    """
    return (type(self),) + self._to_components()


class Return(datatype('Return', ['value']), State):
  """Indicates that a Node successfully returned a value."""

  @classmethod
  def _from_components(cls, components):
    return cls(components[0])

  def _to_components(self):
    return (self.value,)


class Throw(datatype('Throw', ['exc']), State):
  """Indicates that a Node should have been able to return a value, but failed."""


class Runnable(datatype('Runnable', ['func', 'args', 'cacheable']), State):
  """Indicates that the Node is ready to run with the given closure.

  The return value of the Runnable will become the final state of the Node.
  """

  @classmethod
  def _from_components(cls, components):
    return cls(components[0], components[2:], components[1])

  def _to_components(self):
    return (self.func, self.cacheable) + self.args
