# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.parser import Parser


class ParserHierarchy(object):
  """A hierarchy of scoped Parser instances."""
  def __init__(self, env, config, scope_hierarchy, help_request):
    # Scopes are returned in topological order - parents preceding children.
    # This is necessary for the code below to work.
    all_scopes = scope_hierarchy.get_known_scopes()
    self._parser_by_scope = {}
    for scope in all_scopes:
      parent_parser = (None if scope == GLOBAL_SCOPE else
                       self._parser_by_scope[scope_hierarchy.get_parent(scope)])
      self._parser_by_scope[scope] = Parser(env, config, scope, help_request, parent_parser)

  def get_parser_by_scope(self, scope):
    return self._parser_by_scope[scope]
