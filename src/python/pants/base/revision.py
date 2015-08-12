# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from itertools import izip_longest


class Revision(object):
  """Represents a software revision that is comparable to another revision describing the same
  software.
  """
  class BadRevision(Exception):
    """Indicates a problem parsing a revision."""

  @classmethod
  def _parse_atom(cls, atom):
    try:
      return int(atom)
    except ValueError:
      return atom

  @classmethod
  def semver(cls, rev):
    """Attempts to parse a Revision from a semantic version.

    See http://semver.org/ for the full specification.
    """
    def parse_extra(delimiter, value):
      if not value:
        return None, None
      else:
        components = value.split(delimiter, 1)
        return components[0], None if len(components) == 1 else components[1]

    def parse_patch(patch):
      patch, pre_release = parse_extra('-', patch)
      if pre_release:
        pre_release, build = parse_extra('+', pre_release)
      else:
        patch, build = parse_extra('+', patch)
      return patch, pre_release, build

    def parse_components(value):
      if not value:
        yield None
      else:
        for atom in value.split('.'):
          yield cls._parse_atom(atom)

    try:
      major, minor, patch = rev.split('.', 2)
      patch, pre_release, build = parse_patch(patch)
      components = [int(major), int(minor), int(patch)]
      components.extend(parse_components(pre_release))
      components.extend(parse_components(build))
      return cls(*components)
    except ValueError:
      raise cls.BadRevision("Failed to parse '{}' as a semantic version number".format(rev))

  @classmethod
  def lenient(cls, rev):
    """A lenient revision parser that tries to split the version into logical components with
    heuristics inspired by PHP's version_compare.
    """
    rev = re.sub(r'(\d)([a-zA-Z])', r'\1.\2', rev)
    rev = re.sub(r'([a-zA-Z])(\d)', r'\1.\2', rev)
    return cls(*map(cls._parse_atom, re.split(r'[.+_\-]', rev)))

  def __init__(self, *components):
    self._components = components

  @property
  def components(self):
    """Returns a list of this revision's components from most major to most minor."""
    return list(self._components)

  def __cmp__(self, other):
    for ours, theirs in izip_longest(self._components, other._components, fillvalue=0):
      difference = cmp(ours, theirs)
      if difference != 0:
        return difference
    return 0

  def __repr__(self):
    return '{}({})'.format(self.__class__.__name__, ', '.join(map(repr, self._components)))

  def __eq__(self, other):
    return hasattr(other, '_components') and tuple(self._components) == tuple(other._components)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self._components)

  def __str__(self):
    return '.'.join(str(c) for c in self._components)
