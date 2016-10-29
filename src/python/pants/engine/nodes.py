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
