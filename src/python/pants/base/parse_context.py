# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class ParseContext(object):
  """The build file context that context aware objects operate against."""

  def __init__(self, rel_path, type_aliases):
    self._rel_path = rel_path
    self._type_aliases = type_aliases

  def create_object(self, alias, *args, **kwargs):
    """Constructs the type with the given alias using the given args and kwargs."""
    object_type = self._type_aliases.get(alias)
    if object_type is None:
      raise KeyError('There is no type registered for alias {0}'.format(alias))
    return object_type(*args, **kwargs)

  @property
  def rel_path(self):
    """Returns the relative path from the build root to the BUILD file the context aware object is
    executing in.
    """
    return self._rel_path
