# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple


class ScopeInfo(namedtuple('_ScopeInfo', ['scope', 'category'])):
  """Information about a scope."""

  # Symbolic constants for different categories of scope.
  GLOBAL = 'GLOBAL'
  GOAL = 'GOAL'
  TASK = 'TASK'
  GLOBAL_SUBSYSTEM = 'GLOBAL_SUBSYSTEM'
  TASK_SUBSYSTEM = 'TASK_SUBSYSTEM'
  INTERMEDIATE = 'INTERMEDIATE'


  @classmethod
  def for_global_scope(cls):
    return cls('', cls.GLOBAL)
