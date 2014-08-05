# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.parser import Parser


class ParserHierarchy(object):
  """A hierarchy of scoped Parser instances.

  A scope is a dotted string: E.g., compile.java. In this example the compile.java scope is
  enclosed in the compile scope, which is enclosed in the global scope (represented by an
  empty string.)
  """
  def __init__(self, env, config, all_scopes, legacy_parser=None):
    # Sorting ensures that ancestors precede descendants.
    all_scopes = sorted(set(list(all_scopes) + [GLOBAL_SCOPE]))
    self._parser_by_scope = {}
    for scope in all_scopes:
      parent_parser = (None if scope == GLOBAL_SCOPE else
                       self._parser_by_scope[scope.rpartition('.')[0]])
      self._parser_by_scope[scope] = Parser(env, config, scope, parent_parser, legacy_parser)

  def get_parser_by_scope(self, scope):
    return self._parser_by_scope[scope]
