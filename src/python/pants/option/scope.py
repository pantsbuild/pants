# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.objects import DatatypeFieldDecl as F
from pants.util.objects import datatype


GLOBAL_SCOPE = ''
GLOBAL_SCOPE_CONFIG_SECTION = 'GLOBAL'


class ScopeInfo(datatype(['scope', 'category', F('optionable_cls', default_value=None)])):
  """Information about a scope."""

  # Symbolic constants for different categories of scope.
  GLOBAL = 'GLOBAL'
  GOAL = 'GOAL'
  TASK = 'TASK'
  SUBSYSTEM = 'SUBSYSTEM'
  INTERMEDIATE = 'INTERMEDIATE'  # Scope added automatically to fill out the scope hierarchy.

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
