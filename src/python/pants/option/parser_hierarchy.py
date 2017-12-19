# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.config import Config
from pants.option.parser import Parser


class InvalidScopeError(Exception):
  pass

_empty_scope_component_re = re.compile(r'\.\.')


def _validate_full_scope(scope):
  if _empty_scope_component_re.search(scope):
    raise InvalidScopeError(
      "full scope '{}' has at least one empty component".format(scope))


def enclosing_scope(scope):
  """Utility function to return the scope immediately enclosing a given scope."""
  _validate_full_scope(scope)
  return scope.rpartition('.')[0]


def all_enclosing_scopes(scope, allow_global=True):
  """Utility function to return all scopes up to the global scope enclosing a
  given scope."""

  _validate_full_scope(scope)

  # TODO(cosmicexplorer): validate scopes here and/or in `enclosing_scope()`
  # instead of assuming correctness.
  def scope_within_range(tentative_scope):
    if tentative_scope is None:
      return False
    if not allow_global and tentative_scope == GLOBAL_SCOPE:
      return False
    return True

  while scope_within_range(scope):
    yield scope
    scope = (None if scope == GLOBAL_SCOPE else enclosing_scope(scope))


class ParserHierarchy(object):
  """A hierarchy of scoped Parser instances.

  A scope is a dotted string: E.g., compile.java. In this example the compile.java scope is
  enclosed in the compile scope, which is enclosed in the global scope (represented by an
  empty string.)
  """

  def __init__(self, env, config, scope_infos, option_tracker):
    # Sorting ensures that ancestors precede descendants.
    scope_infos = sorted(set(list(scope_infos)), key=lambda si: si.scope)
    self._parser_by_scope = {}
    for scope_info in scope_infos:
      scope = scope_info.scope
      parent_parser = (None if scope == GLOBAL_SCOPE else
                       self._parser_by_scope[enclosing_scope(scope)])
      self._parser_by_scope[scope] = Parser(env, config, scope_info, parent_parser,
                                            option_tracker=option_tracker)

  def get_parser_by_scope(self, scope):
    try:
      return self._parser_by_scope[scope]
    except KeyError:
      raise Config.ConfigValidationError('No such options scope: {}'.format(scope))

  def walk(self, callback):
    """Invoke callback on each parser, in pre-order depth-first order."""
    self._parser_by_scope[GLOBAL_SCOPE].walk(callback)
