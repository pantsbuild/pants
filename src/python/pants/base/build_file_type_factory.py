# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.util.meta import AbstractClass


class BuildFileTypeFactory(AbstractClass):
  """An object that can hydrate types from BUILD files."""

  @abstractproperty
  def produced_types(self):
    """The set of types this factory can produce.

    :rytpe: :class:`collections.Iterable` of BUILD file addressable types.
    """
