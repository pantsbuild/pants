# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple


class ScopeInfo(namedtuple('_ScopeInfo', ['scope', 'category', 'optionable_cls'])):
  """Information about a scope."""

  # Symbolic constants for different categories of scope.
  GLOBAL = 'GLOBAL'
  TASK = 'TASK'
  SUBSYSTEM = 'SUBSYSTEM'
  INTERMEDIATE = 'INTERMEDIATE'  # Scope added automatically to fill out the scope hierarchy.


# Allow the optionable_cls to default to None.
ScopeInfo.__new__.__defaults__ = (None, )
