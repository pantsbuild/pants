# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.struct import Struct


class Variants(Struct):
  """A struct that holds default variant values.

  Variants are key-value pairs representing uniquely identifying parameters for a Node.

  Default variants are usually configured on a Target to be used whenever they are
  not specified by a caller.

  They can be imagined as a dict in terms of dupe handling, but for easier hashability they are
  stored internally as sorted nested tuples of key-value strings.
  """

  @staticmethod
  def merge(left, right):
    """Merges right over left, ensuring that the return value is a tuple of tuples, or None."""
    if not left:
      if right:
        return tuple(right)
      else:
        return None
    if not right:
      return tuple(left)
    # Merge by key, and then return sorted by key.
    merged = dict(left)
    for key, value in right:
      merged[key] = value
    return tuple(sorted(merged.items(), key=lambda x: x[0]))

  def __init__(self, default=None, **kwargs):
    """
    :param dict default: A dict of default variant values.
    """
    # TODO: enforce the type of variants using the Addressable framework.
    super(Variants, self).__init__(default=default, **kwargs)


class Target(Struct):
  """TODO(John Sirois): XXX DOCME"""

  class ConfigurationNotFound(Exception):
    """Indicates a requested configuration of a target could not be found."""

  def __init__(self, name=None, configurations=None, **kwargs):
    """
    :param string name: The name of this target which forms its address in its namespace.
    :param list configurations: The configurations that apply to this target in various contexts.
    """
    super(Target, self).__init__(name=name, **kwargs)

    self.configurations = configurations

  @addressable_list(SubclassesOf(Struct))
  def configurations(self):
    """The configurations that apply to this target in various contexts.

    :rtype list of :class:`pants.engine.exp.configuration.Struct`
    """
