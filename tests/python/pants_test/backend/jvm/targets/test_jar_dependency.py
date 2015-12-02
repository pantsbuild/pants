# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency


class JarDependencyTest(unittest.TestCase):

  def test_jar_dependency_excludes_change_hash(self):
    with_excludes = self._mkjardep()
    without_excludes = self._mkjardep(excludes=[])
    self.assertNotEqual(with_excludes.cache_key(), without_excludes.cache_key())

  def test_jar_dependency_copy(self):
    original = self._mkjardep()
    clone = original.copy()
    self.assertEqual(original, clone)
    original.excludes += (Exclude(org='com.blah', name='blah'),)
    self.assertNotEqual(original, clone)

  def _mkjardep(self, org='foo', name='foo', excludes=(Exclude(org='example.com', name='foo-lib'),)):
    return JarDependency(org=org, name=name, excludes=excludes)
