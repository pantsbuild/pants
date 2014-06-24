# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple


class BuildFileAliases(namedtuple('BuildFileAliases', ['targets', 'objects', 'macros'])):
  """A structure containing set of symbols to be exposed in BUILD files."""

  @classmethod
  def create(cls, targets=None, objects=None, macros=None):
    """A convenience constructor that can accept zero to all alias types."""
    def copy(orig):
      return orig.copy() if orig else {}
    return cls(copy(targets), copy(objects), copy(macros))

  def merge(self, other):
    """Merges a set of build file aliases and returns a new set of aliases containing both.

    Any duplicate aliases from `other` will trump.
    """
    if not isinstance(other, BuildFileAliases):
      raise TypeError('Can only merge other Aliases, given {0}'.format(other))
    all_aliases = self._asdict()
    all_aliases.update(other._asdict())
    return BuildFileAliases(**all_aliases)
