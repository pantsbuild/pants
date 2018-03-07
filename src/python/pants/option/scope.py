# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple


GLOBAL_SCOPE = ''
GLOBAL_SCOPE_CONFIG_SECTION = 'GLOBAL'


class ScopeInfo(namedtuple('_ScopeInfo', ['scope', 'category', 'optionable_cls'])):
  """Information about a scope."""

  # Symbolic constants for different categories of scope.
  GLOBAL = 'GLOBAL'
  GOAL = 'GOAL'
  TASK = 'TASK'
  SUBSYSTEM = 'SUBSYSTEM'
  INTERMEDIATE = 'INTERMEDIATE'  # Scope added automatically to fill out the scope hierarchy.

  def scoped_to(self, client_scope):
    """The Optionable described by this scope, when scoped to the Optionable with client_scope."""
    if client_scope == GLOBAL_SCOPE:
      return self
    return ScopeInfo('{0}.{1}'.format(self.scope, client_scope), self.category, self.optionable_cls)

  def is_scoped(self):
    """Whether this ScopeInfo represents a subsystem scoped to some other optionable."""
    return self.category == self.SUBSYSTEM and '.' in self.scope

  @property
  def description(self):
    return self._optionable_cls_attr('get_description', lambda: '')()

  @property
  def deprecated_scope(self):
    return self._optionable_cls_attr('deprecated_options_scope')

  @property
  def deprecated_scope_removal_version(self):
    return self._optionable_cls_attr('deprecated_options_scope_removal_version')

  def _optionable_cls_attr(self, name, default=None):
    return getattr(self.optionable_cls, name) if self.optionable_cls else default


# Allow the optionable_cls to default to None.
ScopeInfo.__new__.__defaults__ = (None, )
