# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.targets.jar_dependency import JarDependency


from pants_test.base_test import BaseTest


class JarDependenciesTest(BaseTest):

  def test_cache_key(self):
    dep1 = JarDependency(org='com.example', name='foo')
    dep2 = JarDependency(org='com.example', name='foo')
    self.assertEquals(dep1.cache_key(), dep2.cache_key())

    dep3 = JarDependency(org='com.example', name='bar')
    self.assertNotEquals(dep1.cache_key(), dep3.cache_key())


  def test_muable_cache_key(self):
    dep1 = JarDependency(org='com.example', name='foo', mutable=True)
    dep2 = JarDependency(org='com.example', name='foo', mutable=True)
    self.assertNotEquals(dep1.cache_key(), dep2.cache_key())

    # Returns a different key on every invocation
    self.assertNotEquals(dep1.cache_key(), dep1.cache_key())


