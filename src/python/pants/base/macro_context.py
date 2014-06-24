# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class MacroContext(object):
  """The build file context macros operate against."""

  class ScopeError(Exception):
    """Indicates a macro type or function was called outside of macro scope."""

  @classmethod
  def verify(cls, macro_context):
    """Verifies the given macro context is valid and returns it if so."""
    if not isinstance(macro_context, cls):
      raise cls.ScopeError()
    return macro_context

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
    """Returns the relative path from the build root to the BUILD file the macro is executing in."""
    return self._rel_path
