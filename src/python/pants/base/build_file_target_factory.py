# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.util.meta import AbstractClass


class BuildFileTargetFactory(AbstractClass):
  """An object that can hydrate target types from BUILD files."""

  @abstractproperty
  def target_types(self):
    """The set of target types this factory can produce.

    :rytpe: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target` types.
    """
