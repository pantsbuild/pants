# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.parser_hierarchy import InvalidScopeError, all_enclosing_scopes, enclosing_scope
from pants_test.base_test import BaseTest


class TestEnclosingScopeTraversal(BaseTest):
  def test_enclosing_scope(self):
    """The enclosing scope of any non-nested scope should be the global scope,
    and the enclosing scope of a nested scope should be the scope without its
    final component."""
    self.assertEqual(GLOBAL_SCOPE, enclosing_scope(GLOBAL_SCOPE))
    self.assertEqual(GLOBAL_SCOPE, enclosing_scope('scope'))
    self.assertEqual('base', enclosing_scope('base.subscope'))

  def test_all_enclosing_scopes(self):
    """`all_enclosing_scopes` should repeatedly apply `enclosing_scope` to any
    valid single- or multiple- component scope. `all_enclosing_scopes` should
    not yield the global scope if `allow_global=False`."""
    global_closure = list(all_enclosing_scopes(GLOBAL_SCOPE, allow_global=True))
    self.assertEqual(global_closure, [GLOBAL_SCOPE])

    global_closure_excluded = list(all_enclosing_scopes(GLOBAL_SCOPE, allow_global=False))
    self.assertEqual(global_closure_excluded, [])

    base_scope = 'scope'
    base_scope_closure = list(all_enclosing_scopes(base_scope))
    self.assertEqual(base_scope_closure, [base_scope, GLOBAL_SCOPE])

    subscope = 'subscope'
    compound_scope = '{}.{}'.format(base_scope, subscope)
    compound_scope_closure = list(all_enclosing_scopes(compound_scope))
    self.assertEqual(compound_scope_closure, [compound_scope, base_scope, GLOBAL_SCOPE])

    compound_scope_closure_no_global = list(all_enclosing_scopes(compound_scope, allow_global=False))
    self.assertEqual(compound_scope_closure_no_global, [compound_scope, base_scope])

  def test_valid_invalid_scope(self):
    """Scopes with dashes or underscores are treated as a single component, and
    scopes with empty components raise an InvalidScopeError."""
    base_dashed_scope = 'base-scope'
    self.assertEqual(enclosing_scope(base_dashed_scope), GLOBAL_SCOPE)

    subscope_underscore = 'sub_scope'
    self.assertEqual(enclosing_scope(subscope_underscore), GLOBAL_SCOPE)

    compound_scope = '{}.{}'.format(base_dashed_scope, subscope_underscore)
    self.assertEqual(enclosing_scope(compound_scope), base_dashed_scope)
    self.assertEqual(list(all_enclosing_scopes(compound_scope)), [
      compound_scope,
      base_dashed_scope,
      GLOBAL_SCOPE,
    ])

    invalid_scope = 'a.b..c.d'
    with self.assertRaises(InvalidScopeError):
      enclosing_scope(invalid_scope)
    with self.assertRaises(InvalidScopeError):
      # need to bounce to list to get it to error since this is a generator
      list(all_enclosing_scopes(invalid_scope))
