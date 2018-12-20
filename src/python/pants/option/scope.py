# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.util.objects import datatype


GLOBAL_SCOPE = ''
GLOBAL_SCOPE_CONFIG_SECTION = 'GLOBAL'


class Scope(datatype([('scope', str)])):
  """An options scope."""


class ScopeInfo(datatype([
  'scope',
  'category',
  'optionable_cls',
  # A ScopeInfo may have a deprecated_scope (from its associated optionable_cls), which represents a
  # previous/deprecated name for a current/non-deprecated ScopeInfo. It may also be directly
  # deprecated via this `removal_version`, which allows for the deprecation of an entire scope,
  # including that of a SubsystemDependency (ie, deprecation of a dependency on a scoped Subsystem).
  'removal_version',
  'removal_hint',
])):
  """Information about a scope."""

  # Symbolic constants for different categories of scope.
  GLOBAL = 'GLOBAL'
  GOAL = 'GOAL'
  TASK = 'TASK'
  SUBSYSTEM = 'SUBSYSTEM'
  INTERMEDIATE = 'INTERMEDIATE'  # Scope added automatically to fill out the scope hierarchy.

  def __new__(cls, scope, category, optionable_cls=None, removal_version=None, removal_hint=None):
    return super(ScopeInfo, cls).__new__(cls, scope, category, optionable_cls, removal_version, removal_hint)

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
