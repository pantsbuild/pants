# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.option.scope_hierarchy import ScopeHierarchy


class ScopeHierarchyTest(unittest.TestCase):
  def test_compute_inheritance_scope(self):
    def unqualified(scope):
      return ScopeHierarchy.compute_parent(scope, qualified=False)

    def qualified(scope):
      return ScopeHierarchy.compute_parent(scope, qualified=True)

    self.assertEquals('foo.bar', unqualified('foo.bar.baz'))
    self.assertEquals('foo', unqualified('foo.bar'))
    self.assertEquals('', unqualified('foo'))

    self.assertEquals('foo.bar.qual', qualified('foo.bar.baz.qual'))
    self.assertEquals('foo.qual', qualified('foo.bar.qual'))
    self.assertEquals('qual', qualified('foo.qual'))
    self.assertEquals('', qualified('qual'))
